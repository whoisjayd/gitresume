from fastapi import APIRouter, Request

from gitresume.api.routes.oauth_providers import oauth_provider_context, oauth_provider_store
from gitresume.services.model_catalog import LiteLLMModelCatalog, ModelCatalogResponse
from gitresume.services.oauth_provider_store import (
    SUPPORTED_OAUTH_PROVIDERS,
    OAuthProviderStatus,
    disconnected_status,
)

router = APIRouter(prefix="/models")


@router.get("", response_model=ModelCatalogResponse, response_model_by_alias=True)
async def list_models(request: Request) -> ModelCatalogResponse:
    catalog = LiteLLMModelCatalog(await _oauth_statuses(request))
    return ModelCatalogResponse(models=catalog.list_models())


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
