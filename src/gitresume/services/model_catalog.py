from functools import lru_cache
from typing import Any, Literal

import litellm
from pydantic import BaseModel, Field

from gitresume.services.oauth_provider_store import OAuthProviderStatus

ModelMode = Literal["chat", "completion", "responses"]
AuthType = Literal["api_key", "oauth", "none"]

TEXT_MODEL_MODES = {"chat", "completion", "responses"}
NON_TEXT_MODEL_MODES = {
    "audio_speech",
    "audio_transcription",
    "embedding",
    "image_editing",
    "image_generation",
    "moderation",
}
NON_TEXT_MODEL_MARKERS = {
    "audio",
    "dall-e",
    "dalle",
    "diffusion",
    "embedding",
    "flux",
    "image",
    "moderation",
    "speech",
    "stable-diffusion",
    "transcribe",
    "transcription",
    "tts",
    "whisper",
}
NON_TEXT_PROVIDERS = {"fal", "fal-ai", "replicate"}
TEXT_MODEL_MARKERS = {
    "chat",
    "claude",
    "codex",
    "command",
    "deepseek",
    "gemini",
    "gpt",
    "llama",
    "mistral",
    "o1",
    "o3",
    "o4",
    "qwen",
}

OAUTH_TEXT_MODELS: tuple[dict[str, str], ...] = (
    {"id": "github_copilot/gpt-4.1", "provider": "github_copilot", "mode": "chat"},
    {"id": "github_copilot/gpt-4o", "provider": "github_copilot", "mode": "chat"},
    {"id": "github_copilot/claude-3.7-sonnet", "provider": "github_copilot", "mode": "chat"},
    {"id": "chatgpt/gpt-4o", "provider": "chatgpt", "mode": "chat"},
    {"id": "chatgpt/codex-mini-latest", "provider": "chatgpt", "mode": "responses"},
    {"id": "chatgpt/gpt-5-codex", "provider": "chatgpt", "mode": "responses"},
)

OPENROUTER_FREE_MODELS: tuple[dict[str, str], ...] = (
    {
        "id": "openrouter/meta-llama/llama-3.1-8b-instruct:free",
        "provider": "openrouter",
        "mode": "chat",
    },
    {
        "id": "openrouter/mistralai/mistral-7b-instruct:free",
        "provider": "openrouter",
        "mode": "chat",
    },
    {
        "id": "openrouter/google/gemma-2-9b-it:free",
        "provider": "openrouter",
        "mode": "chat",
    },
)


class ModelCatalogEntry(BaseModel):
    id: str
    provider: str
    mode: ModelMode
    display_name: str = Field(serialization_alias="displayName")
    auth_type: AuthType = Field(default="api_key", serialization_alias="authType")
    supports_oauth: bool = Field(default=False, serialization_alias="supportsOauth")
    requires_api_key: bool = Field(default=True, serialization_alias="requiresApiKey")
    is_available: bool = Field(default=True, serialization_alias="isAvailable")
    status: str | None = None
    context_window: int | None = Field(default=None, serialization_alias="contextWindow")


class ModelCatalogResponse(BaseModel):
    models: list[ModelCatalogEntry]


class LiteLLMModelCatalog:
    def __init__(
        self,
        oauth_provider_statuses: dict[str, OAuthProviderStatus] | None = None,
    ) -> None:
        self.oauth_provider_statuses = oauth_provider_statuses

    def list_models(self) -> list[ModelCatalogEntry]:
        if self.oauth_provider_statuses is None:
            return list(_cached_model_catalog_entries(_model_cost_cache_key()))
        return list(_build_model_catalog_entries(self.oauth_provider_statuses))


def find_model_entry(
    model_id: str, oauth_provider_statuses: dict[str, OAuthProviderStatus] | None = None
) -> ModelCatalogEntry | None:
    entries = (
        _cached_model_catalog_entries(_model_cost_cache_key())
        if oauth_provider_statuses is None
        else _build_model_catalog_entries(oauth_provider_statuses)
    )
    return next((entry for entry in entries if entry.id == model_id), None)


def model_mode_for(model_id: str) -> ModelMode:
    entry = find_model_entry(model_id)
    if entry is not None:
        return entry.mode
    return "chat"


def provider_for_model(model_id: str) -> str:
    metadata = getattr(litellm, "model_cost", {}).get(model_id, {})
    if isinstance(metadata, dict) and metadata.get("litellm_provider"):
        return str(metadata["litellm_provider"])
    return model_id.split("/", 1)[0]


@lru_cache(maxsize=1)
def _cached_model_catalog_entries(model_cost_cache_key: int) -> tuple[ModelCatalogEntry, ...]:
    del model_cost_cache_key
    return _build_model_catalog_entries()


def _model_cost_cache_key() -> int:
    return id(getattr(litellm, "model_cost", None))


def _build_model_catalog_entries(
    oauth_provider_statuses: dict[str, OAuthProviderStatus] | None = None,
) -> tuple[ModelCatalogEntry, ...]:
    entries: dict[str, ModelCatalogEntry] = {}
    for model_id, metadata in _iter_litellm_metadata():
        entry = _entry_from_metadata(model_id, metadata)
        if entry is not None:
            entries[entry.id] = entry

    for oauth_model in OAUTH_TEXT_MODELS:
        entry = _entry_from_oauth_model(oauth_model, oauth_provider_statuses)
        entries[entry.id] = entry

    for openrouter_model in OPENROUTER_FREE_MODELS:
        entry = _entry_from_openrouter_free_model(openrouter_model)
        entries.setdefault(entry.id, entry)

    return tuple(sorted(entries.values(), key=lambda entry: (entry.provider, entry.id)))


def _iter_litellm_metadata() -> list[tuple[str, dict[str, Any]]]:
    model_cost = getattr(litellm, "model_cost", None)
    if not isinstance(model_cost, dict):
        return []
    return [
        (str(model_id), metadata)
        for model_id, metadata in model_cost.items()
        if isinstance(metadata, dict)
    ]


def _entry_from_metadata(model_id: str, metadata: dict[str, Any]) -> ModelCatalogEntry | None:
    provider = str(metadata.get("litellm_provider") or model_id.split("/", 1)[0])
    mode = _normalize_mode(metadata.get("mode"), model_id=model_id, provider=provider)
    if mode is None:
        return None
    return ModelCatalogEntry(
        id=model_id,
        provider=provider,
        mode=mode,
        display_name=_display_name(model_id),
        auth_type="api_key",
        supports_oauth=False,
        requires_api_key=True,
        is_available=True,
        status=None,
        context_window=_context_window(metadata),
    )


def _entry_from_oauth_model(
    oauth_model: dict[str, str],
    oauth_provider_statuses: dict[str, OAuthProviderStatus] | None = None,
) -> ModelCatalogEntry:
    mode = _normalize_mode(oauth_model["mode"], model_id=oauth_model["id"]) or "chat"
    provider = oauth_model["provider"]
    provider_status = (oauth_provider_statuses or {}).get(provider)
    is_available = bool(
        provider_status and provider_status.connected and provider_status.executable
    )
    status = None if is_available else _oauth_unavailable_status(provider, provider_status)
    return ModelCatalogEntry(
        id=oauth_model["id"],
        provider=provider,
        mode=mode,
        display_name=_display_name(oauth_model["id"]),
        auth_type="oauth",
        supports_oauth=True,
        requires_api_key=False,
        is_available=is_available,
        status=status,
    )


def _entry_from_openrouter_free_model(openrouter_model: dict[str, str]) -> ModelCatalogEntry:
    mode = _normalize_mode(openrouter_model["mode"], model_id=openrouter_model["id"]) or "chat"
    return ModelCatalogEntry(
        id=openrouter_model["id"],
        provider=openrouter_model["provider"],
        mode=mode,
        display_name=_display_name(openrouter_model["id"]),
        auth_type="api_key",
        supports_oauth=False,
        requires_api_key=True,
        is_available=True,
        status=(
            "OpenRouter :free model. Requires an OpenRouter API key; provider "
            "availability and rate limits are controlled by OpenRouter."
        ),
    )


def _oauth_unavailable_status(provider: str, provider_status: OAuthProviderStatus | None) -> str:
    if provider_status is not None and provider_status.status:
        return provider_status.status
    return (
        f"Connect {provider} with a manually configured server-stored OAuth token. "
        "Browser device-code flow is not exposed by the current in-process LiteLLM integration."
    )


def _normalize_mode(
    value: Any, *, model_id: str | None = None, provider: str | None = None
) -> ModelMode | None:
    if value is None:
        return _infer_missing_mode(model_id, provider)
    mode = str(value).lower()
    if mode in NON_TEXT_MODEL_MODES:
        return None
    if mode in TEXT_MODEL_MODES:
        return mode  # type: ignore[return-value]
    return None


def _infer_missing_mode(model_id: str | None, provider: str | None) -> ModelMode | None:
    if not model_id:
        return None
    normalized_id = model_id.lower()
    normalized_provider = (provider or model_id.split("/", 1)[0]).lower()
    if normalized_provider in NON_TEXT_PROVIDERS:
        return None
    if any(marker in normalized_id for marker in NON_TEXT_MODEL_MARKERS):
        return None
    if any(marker in normalized_id for marker in TEXT_MODEL_MARKERS):
        return "chat"
    return None


def _display_name(model_id: str) -> str:
    return model_id.split("/", 1)[-1].replace("-", " ").replace("_", " ").title()


def _context_window(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("max_input_tokens") or metadata.get("context_window")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
