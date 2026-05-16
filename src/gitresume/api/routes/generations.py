import json
import logging
import re
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from gitresume.api.dependencies import get_generation_state_service, get_generation_task_dispatcher
from gitresume.api.routes.oauth_providers import oauth_provider_context
from gitresume.api.routes.settings import _settings_context
from gitresume.core.config import Settings
from gitresume.core.crypto import StringEncryptor
from gitresume.schemas.generation import (
    GenerationCreateRequest,
    GenerationCreateResponse,
    GenerationEvent,
    GenerationState,
)
from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.generation_task_dispatcher import GenerationTaskDispatcher
from gitresume.services.model_catalog import find_model_entry, provider_for_model
from gitresume.services.oauth_provider_store import (
    SUPPORTED_OAUTH_PROVIDERS,
    OAuthProviderStatus,
    RedisOAuthProviderStore,
    disconnected_status,
)
from gitresume.services.settings_store import RedisSettingsStore, StoredProviderKey

router = APIRouter(prefix="/generations")
generation_state_dependency = Depends(get_generation_state_service)
generation_dispatcher_dependency = Depends(get_generation_task_dispatcher)
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=GenerationCreateResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation(
    request: GenerationCreateRequest,
    http_request: Request,
    state_service: RedisGenerationStateService = generation_state_dependency,
    dispatcher: GenerationTaskDispatcher = generation_dispatcher_dependency,
) -> GenerationCreateResponse:
    request.provider_key_scope = None
    request.oauth_provider_scope = None
    request.owner_scope = None
    oauth_statuses = await _oauth_provider_statuses(http_request)
    request.owner_scope = _generation_owner_scope(http_request)
    request.model = await _effective_generation_model(http_request, request.model)
    _validate_contribution_analysis_request(http_request.app.state.settings, request)
    if request.model is not None:
        model_entry = find_model_entry(request.model, oauth_statuses)
        if model_entry is None:
            if request.model.split("/", 1)[0] in SUPPORTED_OAUTH_PROVIDERS:
                raise HTTPException(status_code=422, detail=f"Unknown model: {request.model}")
        elif not model_entry.is_available:
            raise HTTPException(
                status_code=422,
                detail=f"Selected model is not available: {model_entry.status or request.model}",
            )
        if model_entry is not None and model_entry.auth_type == "oauth":
            request.oauth_provider_scope = _oauth_provider_scope(http_request)
    request.provider_key_scope = _provider_key_scope(http_request, request)
    await _validate_provider_key_selection(http_request, request)
    generation_id = f"gen-{uuid4().hex}"
    state_created = False
    state_may_exist = False
    try:
        state_may_exist = True
        await state_service.create_generation(generation_id, request)
        state_created = True
        if request.github_token:
            await state_service.store_github_token(
                generation_id, request.github_token.get_secret_value()
            )
        if request.provider_api_key:
            await state_service.store_provider_api_key(
                generation_id, request.provider_api_key.get_secret_value()
            )
        task_id = await dispatcher.enqueue(generation_id)
        await state_service.set_task_id(generation_id, task_id)
    except Exception as error:
        if state_created or await _generation_state_exists_when_possible(
            state_service, generation_id, state_may_exist=state_may_exist
        ):
            await _best_effort_fail_created_generation(state_service, generation_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue generation job.",
        ) from error
    return GenerationCreateResponse(
        generation_id=generation_id,
        status_url=f"/api/generations/{generation_id}",
        events_url=f"/api/generations/{generation_id}/events",
        redirect_path=f"/generations/{generation_id}",
    )


def _validate_contribution_analysis_request(
    settings: Settings, request: GenerationCreateRequest
) -> None:
    if request.analysis_author is None:
        return
    if not settings.enable_guided_analysis or not settings.enable_contribution_analysis:
        raise HTTPException(status_code=422, detail="Contribution analysis is not enabled.")
    if request.analysis_days is None:
        request.analysis_days = settings.contribution_analysis_default_days


def _generation_owner_scope(http_request: Request) -> str | None:
    settings = http_request.app.state.settings
    if settings.app_mode != "hosted":
        return None
    session = getattr(http_request, "session", {})
    if not session.get("is_authenticated") or not session.get("github_user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub login is required to create a generation in hosted mode.",
        )
    return f"user:{session['github_user_id']}"


async def _effective_generation_model(http_request: Request, requested_model: str | None) -> str:
    if requested_model:
        return requested_model
    settings = http_request.app.state.settings
    context = _settings_context(http_request)
    if context.enabled:
        store = _settings_store(http_request, context.settings)
        try:
            if store is not None:
                dashboard = await store.get_dashboard_settings(context.scope)
                if dashboard.default_model:
                    return dashboard.default_model
        finally:
            await _close_owned_store_redis(store)
    return settings.ai_model


async def _oauth_provider_statuses(http_request: Request) -> dict[str, OAuthProviderStatus]:
    context = oauth_provider_context(http_request)
    store = _oauth_provider_store(http_request, context.settings) if context.enabled else None
    if store is None:
        reason = context.disabled_reason if not context.enabled else None
        return {
            provider: disconnected_status(provider, reason)
            for provider in SUPPORTED_OAUTH_PROVIDERS
        }
    try:
        statuses = await store.list_statuses(context.scope, SUPPORTED_OAUTH_PROVIDERS)
        return {status.provider: status for status in statuses}
    finally:
        await _close_owned_store_redis(store)


def _oauth_provider_scope(http_request: Request) -> str:
    context = oauth_provider_context(http_request)
    if not context.enabled:
        error_status = (
            status.HTTP_401_UNAUTHORIZED if context.login_required else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=error_status,
            detail=context.disabled_reason or "OAuth provider connection is required.",
        )
    return context.scope


def _provider_key_scope(http_request: Request, request: GenerationCreateRequest) -> str | None:
    if request.provider_key_id is None:
        return None
    settings = http_request.app.state.settings
    if settings.app_mode != "hosted":
        return "global"
    session = getattr(http_request, "session", {})
    if not session.get("is_authenticated") or not session.get("github_user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub login is required to use a saved provider key.",
        )
    return f"user:{session['github_user_id']}"


async def _validate_provider_key_selection(
    http_request: Request,
    request: GenerationCreateRequest,
) -> None:
    if request.provider_key_id is None:
        return
    if request.model is None:
        raise HTTPException(
            status_code=422, detail="A model is required to use a saved provider key."
        )
    context = _settings_context(http_request)
    if not context.enabled:
        status_code = (
            status.HTTP_401_UNAUTHORIZED if context.login_required else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=status_code,
            detail=context.disabled_reason or "Saved provider keys are not enabled.",
        )
    store = _settings_store(http_request, context.settings)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is required for saved BYOK settings.",
        )
    try:
        key = await store.get_provider_key(
            request.provider_key_scope or context.scope, request.provider_key_id
        )
        if key is None:
            raise HTTPException(status_code=422, detail="Unknown provider key.")
        _validate_provider_key_matches_model(key, request.model)
    finally:
        await _close_owned_store_redis(store)


def _settings_store(request: Request, settings: Settings) -> RedisSettingsStore | None:
    if settings.settings_encryption_key is None:
        return None
    redis = getattr(request.app.state, "redis", None)
    owns_redis = False
    if redis is None:
        if not settings.redis_url:
            return None
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        owns_redis = True
    store = RedisSettingsStore(
        redis,
        StringEncryptor(settings.settings_encryption_key.get_secret_value()),
    )
    if owns_redis:
        store._gitresume_owned_redis = redis
    return store


def _oauth_provider_store(request: Request, settings: Settings) -> RedisOAuthProviderStore | None:
    if settings.settings_encryption_key is None:
        return None
    redis = getattr(request.app.state, "redis", None)
    owns_redis = False
    if redis is None:
        if not settings.redis_url:
            return None
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        owns_redis = True
    store = RedisOAuthProviderStore(
        redis,
        StringEncryptor(settings.settings_encryption_key.get_secret_value()),
        ttl_seconds=(
            settings.session_cookie_max_age_seconds if settings.app_mode == "hosted" else None
        ),
    )
    if owns_redis:
        store._gitresume_owned_redis = redis
    return store


async def _close_owned_store_redis(store: object | None) -> None:
    redis = getattr(store, "_gitresume_owned_redis", None)
    if redis is None:
        return
    try:
        await redis.aclose()
    except Exception:
        logger.warning("Failed to close generation route Redis client", exc_info=True)


async def _best_effort_fail_created_generation(
    state_service: RedisGenerationStateService,
    generation_id: str,
) -> None:
    for cleanup in (
        state_service.delete_github_token,
        state_service.delete_provider_api_key,
    ):
        try:
            await cleanup(generation_id)
        except Exception:
            logger.warning("Failed to clean up generation credential", exc_info=True)
    try:
        await state_service.fail_generation(generation_id, "Failed to enqueue generation job.")
    except Exception:
        logger.warning("Failed to mark generation failed after enqueue setup error", exc_info=True)


async def _generation_state_exists_when_possible(
    state_service: RedisGenerationStateService,
    generation_id: str,
    *,
    state_may_exist: bool,
) -> bool:
    if not state_may_exist:
        return False
    try:
        return await state_service.get_generation(generation_id) is not None
    except Exception:
        logger.warning("Failed to inspect partial generation state", exc_info=True)
        return False


def _validate_provider_key_matches_model(key: StoredProviderKey, model: str) -> None:
    if not key.is_active:
        raise HTTPException(status_code=403, detail="Provider key is inactive.")
    model_provider = provider_for_model(model)
    if key.provider != model_provider:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Provider key provider {key.provider} "
                f"does not match model provider {model_provider}."
            ),
        )
    if key.model is not None and key.model != model:
        raise HTTPException(
            status_code=422,
            detail=f"Provider key is restricted to model {key.model}.",
        )


@router.get(
    "/{generation_id}",
    response_model=GenerationState,
    response_model_by_alias=True,
    response_model_exclude_none=True,
)
async def get_generation(
    generation_id: str,
    http_request: Request,
    state_service: RedisGenerationStateService = generation_state_dependency,
) -> GenerationState:
    state = await state_service.get_generation(generation_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    _ensure_generation_owner(http_request, state)
    return state


@router.get("/{generation_id}/events")
async def get_generation_events(
    generation_id: str,
    http_request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    state_service: RedisGenerationStateService = generation_state_dependency,
) -> EventSourceResponse:
    state = await state_service.get_generation(generation_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    _ensure_generation_owner(http_request, state)
    if last_event_id is not None and not re.fullmatch(r"\d+-\d+", last_event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be a Redis stream ID.",
        )

    async def events() -> AsyncIterator[dict[str, str]]:
        after_id = last_event_id or "0-0"
        for stream_id, event in await state_service.replay_events_with_ids(
            generation_id, after_id=after_id
        ):
            after_id = stream_id
            yield _sse_event(event, stream_id)
            if event.status is not None and event.status.value in {"succeeded", "failed"}:
                return
        async for stream_id, event in state_service.stream_events_with_ids(
            generation_id, after_id=after_id
        ):
            yield _sse_event(event, stream_id)

    return EventSourceResponse(events())


def _ensure_generation_owner(http_request: Request, state: GenerationState) -> None:
    settings = http_request.app.state.settings
    if settings.app_mode != "hosted":
        return
    session = getattr(http_request, "session", {})
    if not session.get("is_authenticated") or not session.get("github_user_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    if state.owner_scope != f"user:{session['github_user_id']}":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")


def _sse_event(event: GenerationEvent, stream_id: str) -> dict[str, str]:
    return {
        "id": stream_id,
        "event": event.event_type,
        "data": json.dumps(event.model_dump(by_alias=True, mode="json"), separators=(",", ":")),
    }
