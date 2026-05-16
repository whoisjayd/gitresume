from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from redis.asyncio import Redis

from gitresume.core.config import Settings
from gitresume.core.crypto import StringEncryptor
from gitresume.services.oauth_login_service import OAuthLoginJob, OAuthLoginService
from gitresume.services.oauth_provider_store import (
    SUPPORTED_OAUTH_PROVIDERS,
    OAuthProviderCredentialInput,
    OAuthProviderStatus,
    RedisOAuthProviderStore,
    disconnected_status,
)

router = APIRouter(prefix="/oauth-providers")

DISABLED_BY_CONFIG = (
    "OAuth provider connections are disabled until SETTINGS_ENCRYPTION_KEY is configured."
)
DISABLED_BY_AUTH = "GitHub login is required to manage OAuth provider connections in hosted mode."
DISABLED_BY_REDIS = "Redis is required for OAuth provider connections."


class OAuthProvidersResponse(BaseModel):
    providers: list[OAuthProviderStatus]


class OAuthProviderConnectRequest(BaseModel):
    access_token: SecretStr = Field(validation_alias="accessToken", exclude=True, repr=False)
    refresh_token: SecretStr | None = Field(
        default=None,
        validation_alias="refreshToken",
        exclude=True,
        repr=False,
    )
    account_label: str | None = Field(default=None, validation_alias="accountLabel")
    expires_at: datetime | None = Field(default=None, validation_alias="expiresAt")

    @field_validator("access_token")
    @classmethod
    def reject_blank_access_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("accessToken must not be empty.")
        return value


class OAuthProviderAccountUpdateRequest(BaseModel):
    access_token: SecretStr = Field(validation_alias="accessToken", exclude=True, repr=False)
    refresh_token: SecretStr | None = Field(
        default=None,
        validation_alias="refreshToken",
        exclude=True,
        repr=False,
    )
    expires_at: datetime | None = Field(default=None, validation_alias="expiresAt")

    @field_validator("access_token")
    @classmethod
    def reject_blank_access_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("accessToken must not be empty.")
        return value


class OAuthLoginStartResponse(BaseModel):
    job_id: str = Field(serialization_alias="jobId")
    status_url: str = Field(serialization_alias="statusUrl")


class OAuthProviderContext(BaseModel):
    settings: Settings = Field(exclude=True)
    scope: str
    enabled: bool
    login_required: bool
    disabled_reason: str | None = None

    model_config = {"arbitrary_types_allowed": True}


@router.get("", response_model=OAuthProvidersResponse, response_model_by_alias=True)
async def list_oauth_providers(request: Request) -> OAuthProvidersResponse:
    context = oauth_provider_context(request)
    store = oauth_provider_store(request, context.settings) if context.enabled else None
    if store is None:
        reason = context.disabled_reason if not context.enabled else DISABLED_BY_REDIS
        return OAuthProvidersResponse(
            providers=[
                disconnected_status(provider, reason) for provider in SUPPORTED_OAUTH_PROVIDERS
            ]
        )
    return OAuthProvidersResponse(
        providers=await store.list_statuses(context.scope, SUPPORTED_OAUTH_PROVIDERS)
    )


@router.post(
    "/{provider}/login",
    response_model=OAuthLoginStartResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_oauth_provider_login(provider: str, request: Request) -> OAuthLoginStartResponse:
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider.")
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    service = require_oauth_login_service(request, context.settings, store, context.scope)
    try:
        job = await service.start(provider)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return OAuthLoginStartResponse(job_id=job.job_id, status_url=job.status_url)


@router.get(
    "/login-jobs/{job_id}",
    response_model=OAuthLoginJob,
    response_model_by_alias=True,
)
async def get_oauth_provider_login_job(job_id: str, request: Request) -> OAuthLoginJob:
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    service = require_oauth_login_service(request, context.settings, store, context.scope)
    job = await service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="OAuth login job not found.")
    return job


@router.post(
    "/{provider}/connect",
    response_model=OAuthProviderStatus,
    response_model_by_alias=True,
)
async def connect_oauth_provider(
    provider: str, body: OAuthProviderConnectRequest, request: Request
) -> OAuthProviderStatus:
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider.")
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    return await store.connect(
        context.scope,
        OAuthProviderCredentialInput(
            provider=provider,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
            account_label=body.account_label,
            expires_at=body.expires_at,
        ),
    )


@router.put(
    "/{provider}/accounts/{account_id}",
    response_model=OAuthProviderStatus,
    response_model_by_alias=True,
)
async def update_oauth_provider_account(
    provider: str,
    account_id: str,
    body: OAuthProviderAccountUpdateRequest,
    request: Request,
) -> OAuthProviderStatus:
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider.")
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    try:
        return await store.update_account_token(
            context.scope,
            provider,
            account_id,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
            expires_at=body.expires_at,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="OAuth account not found.") from error


@router.delete("/{provider}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_oauth_provider_account(
    provider: str, account_id: str, request: Request
) -> Response:
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider.")
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    deleted = await store.disconnect_account(context.scope, provider, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OAuth account not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_oauth_provider(provider: str, request: Request) -> Response:
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported OAuth provider.")
    context = oauth_provider_context(request)
    ensure_oauth_enabled(context)
    store = require_oauth_provider_store(request, context.settings)
    await store.disconnect(context.scope, provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def oauth_provider_context(request: Request) -> OAuthProviderContext:
    settings: Settings = request.app.state.settings
    session: dict[str, Any] = getattr(request, "session", {})
    authenticated = bool(session.get("is_authenticated"))
    if not settings.settings_encryption_key:
        return OAuthProviderContext(
            settings=settings,
            scope="global",
            enabled=False,
            login_required=settings.app_mode == "hosted" and not authenticated,
            disabled_reason=DISABLED_BY_CONFIG,
        )
    if settings.app_mode == "hosted":
        if not authenticated or not session.get("github_user_id"):
            return OAuthProviderContext(
                settings=settings,
                scope="user:anonymous",
                enabled=False,
                login_required=True,
                disabled_reason=DISABLED_BY_AUTH,
            )
        return OAuthProviderContext(
            settings=settings,
            scope=f"user:{session['github_user_id']}",
            enabled=True,
            login_required=False,
        )
    return OAuthProviderContext(
        settings=settings,
        scope="global",
        enabled=True,
        login_required=False,
    )


def oauth_provider_store(request: Request, settings: Settings) -> RedisOAuthProviderStore | None:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        if not settings.redis_url:
            return None
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
    if settings.settings_encryption_key is None:
        return None
    return RedisOAuthProviderStore(
        redis,
        StringEncryptor(settings.settings_encryption_key.get_secret_value()),
        ttl_seconds=(
            settings.session_cookie_max_age_seconds if settings.app_mode == "hosted" else None
        ),
    )


def require_oauth_provider_store(request: Request, settings: Settings) -> RedisOAuthProviderStore:
    store = oauth_provider_store(request, settings)
    if store is None:
        raise HTTPException(status_code=503, detail=DISABLED_BY_REDIS)
    return store


def require_oauth_login_service(
    request: Request,
    settings: Settings,
    store: RedisOAuthProviderStore,
    scope: str,
) -> OAuthLoginService:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        if not settings.redis_url:
            raise HTTPException(status_code=503, detail=DISABLED_BY_REDIS)
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return OAuthLoginService(redis, settings, store, scope)


def ensure_oauth_enabled(context: OAuthProviderContext) -> None:
    if context.enabled:
        return
    if context.login_required:
        raise HTTPException(status_code=401, detail=context.disabled_reason or DISABLED_BY_AUTH)
    raise HTTPException(status_code=403, detail=context.disabled_reason or DISABLED_BY_CONFIG)
