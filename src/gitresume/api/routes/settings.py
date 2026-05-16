from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr
from redis.asyncio import Redis

from gitresume.api.routes.oauth_providers import oauth_provider_context, oauth_provider_store
from gitresume.core.config import Settings
from gitresume.core.crypto import StringEncryptor
from gitresume.services.model_catalog import find_model_entry, provider_for_model
from gitresume.services.oauth_provider_store import (
    SUPPORTED_OAUTH_PROVIDERS,
    OAuthProviderStatus,
    disconnected_status,
)
from gitresume.services.settings_store import (
    ProviderKeyInput,
    RedisSettingsStore,
    StoredProviderKey,
)

router = APIRouter(prefix="/settings")

DISABLED_BY_CONFIG = "Saved BYOK is disabled by server configuration."
DISABLED_BY_AUTH = "GitHub login is required to manage saved provider keys in hosted mode."
DISABLED_BY_REDIS = "Redis is required for saved BYOK settings."


class ProviderKeyMetadataResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    provider: str
    label: str
    model: str | None = None
    created_at: datetime = Field(serialization_alias="createdAt")
    last_used_at: datetime | None = Field(default=None, serialization_alias="lastUsedAt")
    is_active: bool = Field(default=True, serialization_alias="isActive")


class DashboardSettingsResponse(BaseModel):
    app_mode: Literal["self_hosted", "hosted"] = Field(serialization_alias="appMode")
    allow_saved_byok: bool = Field(serialization_alias="allowSavedByok")
    saved_keys_enabled: bool = Field(serialization_alias="savedKeysEnabled")
    login_required: bool = Field(serialization_alias="loginRequired")
    default_model: str | None = Field(default=None, serialization_alias="defaultModel")
    provider_keys: list[ProviderKeyMetadataResponse] = Field(
        default_factory=list, serialization_alias="providerKeys"
    )
    disabled_reason: str | None = Field(default=None, serialization_alias="disabledReason")


class ProviderKeyCreateRequest(BaseModel):
    provider: str
    label: str
    secret: SecretStr = Field(exclude=True, repr=False)
    model: str | None = None


class DefaultModelUpdateRequest(BaseModel):
    model: str | None = None


@router.get("", response_model=DashboardSettingsResponse, response_model_by_alias=True)
async def get_settings(request: Request) -> DashboardSettingsResponse:
    context = _settings_context(request)
    if not context.enabled:
        return _disabled_response(context)
    store = _settings_store(request, context.settings)
    if store is None:
        return _disabled_response(context, DISABLED_BY_REDIS)
    dashboard = await store.get_dashboard_settings(context.scope)
    return _response_from_dashboard(context, dashboard.default_model, dashboard.provider_keys)


@router.put(
    "/default-model",
    response_model=DashboardSettingsResponse,
    response_model_by_alias=True,
)
async def set_default_model(
    body: DefaultModelUpdateRequest,
    request: Request,
) -> DashboardSettingsResponse:
    context = _settings_context(request)
    _ensure_enabled(context)
    await _validate_settings_model(body.model, request)
    store = _require_settings_store(request, context.settings)
    dashboard = await store.set_default_model(context.scope, body.model)
    return _response_from_dashboard(context, dashboard.default_model, dashboard.provider_keys)


@router.post(
    "/provider-keys",
    response_model=ProviderKeyMetadataResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_key(
    body: ProviderKeyCreateRequest,
    request: Request,
) -> StoredProviderKey:
    context = _settings_context(request)
    _ensure_enabled(context)
    await _validate_provider_key_model(body.provider, body.model, request)
    store = _require_settings_store(request, context.settings)
    return await store.save_provider_key(
        context.scope,
        ProviderKeyInput(
            provider=body.provider,
            label=body.label,
            secret=body.secret,
            model=body.model,
        ),
    )


@router.delete("/provider-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(key_id: str, request: Request) -> Response:
    context = _settings_context(request)
    _ensure_enabled(context)
    store = _require_settings_store(request, context.settings)
    await store.delete_provider_key(context.scope, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SettingsContext(BaseModel):
    settings: Settings = Field(exclude=True)
    scope: str
    enabled: bool
    login_required: bool
    disabled_reason: str | None = None

    model_config = {"arbitrary_types_allowed": True}


def _settings_context(request: Request) -> SettingsContext:
    settings: Settings = request.app.state.settings
    session: dict[str, Any] = getattr(request, "session", {})
    authenticated = bool(session.get("is_authenticated"))
    if not settings.allow_saved_byok or not settings.settings_encryption_key:
        return SettingsContext(
            settings=settings,
            scope="global",
            enabled=False,
            login_required=settings.app_mode == "hosted" and not authenticated,
            disabled_reason=DISABLED_BY_CONFIG,
        )
    if settings.app_mode == "hosted":
        if not authenticated or not session.get("github_user_id"):
            return SettingsContext(
                settings=settings,
                scope="user:anonymous",
                enabled=False,
                login_required=True,
                disabled_reason=DISABLED_BY_AUTH,
            )
        return SettingsContext(
            settings=settings,
            scope=f"user:{session['github_user_id']}",
            enabled=True,
            login_required=False,
        )
    return SettingsContext(settings=settings, scope="global", enabled=True, login_required=False)


def _settings_store(request: Request, settings: Settings) -> RedisSettingsStore | None:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        if not settings.redis_url:
            return None
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
    if settings.settings_encryption_key is None:
        return None
    return RedisSettingsStore(
        redis,
        StringEncryptor(settings.settings_encryption_key.get_secret_value()),
    )


def _require_settings_store(request: Request, settings: Settings) -> RedisSettingsStore:
    store = _settings_store(request, settings)
    if store is None:
        raise HTTPException(status_code=503, detail=DISABLED_BY_REDIS)
    return store


async def _validate_settings_model(model: str | None, request: Request) -> None:
    if model is None:
        return
    entry = find_model_entry(model, await _oauth_statuses(request))
    if entry is None:
        raise HTTPException(status_code=422, detail=f"Unknown model: {model}")
    if not entry.is_available:
        raise HTTPException(
            status_code=422,
            detail=f"Selected model is not available: {entry.status or model}",
        )


async def _validate_provider_key_model(provider: str, model: str | None, request: Request) -> None:
    await _validate_settings_model(model, request)
    if model is None:
        return
    model_provider = provider_for_model(model)
    if provider != model_provider:
        raise HTTPException(
            status_code=422,
            detail=f"Provider {provider} does not match model provider {model_provider}.",
        )


async def _oauth_statuses(request: Request) -> dict[str, OAuthProviderStatus]:
    context = oauth_provider_context(request)
    store = oauth_provider_store(request, context.settings) if context.enabled else None
    if store is None:
        reason = context.disabled_reason if not context.enabled else None
        return {
            provider: disconnected_status(provider, reason)
            for provider in SUPPORTED_OAUTH_PROVIDERS
        }
    statuses = await store.list_statuses(context.scope, SUPPORTED_OAUTH_PROVIDERS)
    return {status.provider: status for status in statuses}


def _ensure_enabled(context: SettingsContext) -> None:
    if context.enabled:
        return
    if context.login_required:
        raise HTTPException(status_code=401, detail=context.disabled_reason or DISABLED_BY_AUTH)
    raise HTTPException(status_code=403, detail=context.disabled_reason or DISABLED_BY_CONFIG)


def _disabled_response(
    context: SettingsContext, reason: str | None = None
) -> DashboardSettingsResponse:
    return DashboardSettingsResponse(
        app_mode=context.settings.app_mode,
        allow_saved_byok=context.settings.allow_saved_byok,
        saved_keys_enabled=False,
        login_required=context.login_required,
        default_model=None,
        provider_keys=[],
        disabled_reason=reason or context.disabled_reason,
    )


def _response_from_dashboard(
    context: SettingsContext,
    default_model: str | None,
    provider_keys: list[StoredProviderKey],
) -> DashboardSettingsResponse:
    return DashboardSettingsResponse(
        app_mode=context.settings.app_mode,
        allow_saved_byok=context.settings.allow_saved_byok,
        saved_keys_enabled=True,
        login_required=context.login_required,
        default_model=default_model,
        provider_keys=[ProviderKeyMetadataResponse.model_validate(key) for key in provider_keys],
    )
