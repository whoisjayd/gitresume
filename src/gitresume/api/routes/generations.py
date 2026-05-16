import json
import re
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from gitresume.api.dependencies import get_generation_state_service, get_generation_task_dispatcher
from gitresume.api.routes.oauth_providers import oauth_provider_context, oauth_provider_store
from gitresume.schemas.generation import (
    GenerationCreateRequest,
    GenerationCreateResponse,
    GenerationEvent,
    GenerationState,
)
from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.generation_task_dispatcher import GenerationTaskDispatcher
from gitresume.services.model_catalog import find_model_entry
from gitresume.services.oauth_provider_store import (
    SUPPORTED_OAUTH_PROVIDERS,
    OAuthProviderStatus,
    disconnected_status,
)

router = APIRouter(prefix="/generations")
generation_state_dependency = Depends(get_generation_state_service)
generation_dispatcher_dependency = Depends(get_generation_task_dispatcher)


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
    oauth_statuses = await _oauth_provider_statuses(http_request)
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
    generation_id = f"gen-{uuid4().hex}"
    await state_service.create_generation(generation_id, request)
    if request.github_token:
        await state_service.store_github_token(
            generation_id, request.github_token.get_secret_value()
        )
    if request.provider_api_key:
        await state_service.store_provider_api_key(
            generation_id, request.provider_api_key.get_secret_value()
        )
    try:
        task_id = await dispatcher.enqueue(generation_id)
    except Exception as error:
        await state_service.delete_github_token(generation_id)
        await state_service.delete_provider_api_key(generation_id)
        await state_service.fail_generation(generation_id, "Failed to enqueue generation job.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue generation job.",
        ) from error
    await state_service.set_task_id(generation_id, task_id)
    return GenerationCreateResponse(
        generation_id=generation_id,
        status_url=f"/api/generations/{generation_id}",
        events_url=f"/api/generations/{generation_id}/events",
        redirect_path=f"/generations/{generation_id}",
    )


async def _oauth_provider_statuses(http_request: Request) -> dict[str, OAuthProviderStatus]:
    context = oauth_provider_context(http_request)
    store = oauth_provider_store(http_request, context.settings) if context.enabled else None
    if store is None:
        reason = context.disabled_reason if not context.enabled else None
        return {
            provider: disconnected_status(provider, reason)
            for provider in SUPPORTED_OAUTH_PROVIDERS
        }
    statuses = await store.list_statuses(context.scope, SUPPORTED_OAUTH_PROVIDERS)
    return {status.provider: status for status in statuses}


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


@router.get(
    "/{generation_id}",
    response_model=GenerationState,
    response_model_by_alias=True,
    response_model_exclude_none=True,
)
async def get_generation(
    generation_id: str,
    state_service: RedisGenerationStateService = generation_state_dependency,
) -> GenerationState:
    state = await state_service.get_generation(generation_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
    return state


@router.get("/{generation_id}/events")
async def get_generation_events(
    generation_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    state_service: RedisGenerationStateService = generation_state_dependency,
) -> EventSourceResponse:
    if await state_service.get_generation(generation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found.")
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


def _sse_event(event: GenerationEvent, stream_id: str) -> dict[str, str]:
    return {
        "id": stream_id,
        "event": event.event_type,
        "data": json.dumps(event.model_dump(by_alias=True, mode="json"), separators=(",", ":")),
    }
