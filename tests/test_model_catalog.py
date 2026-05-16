from fastapi.testclient import TestClient

from gitresume.core.config import Settings
from gitresume.main import create_app


def test_model_catalog_uses_litellm_metadata_and_filters_non_text_modes(
    monkeypatch,
) -> None:
    from gitresume.services import model_catalog

    monkeypatch.setattr(
        model_catalog.litellm,
        "model_cost",
        {
            "openai/gpt-4o-mini": {
                "litellm_provider": "openai",
                "mode": "chat",
                "max_input_tokens": 128000,
            },
            "openai/text-embedding-3-small": {
                "litellm_provider": "openai",
                "mode": "embedding",
            },
            "fal/image": {
                "litellm_provider": "fal",
                "mode": "image_generation",
            },
        },
        raising=False,
    )

    entries = model_catalog.LiteLLMModelCatalog().list_models()

    ids = [entry.id for entry in entries]
    assert "openai/gpt-4o-mini" in ids
    assert "openai/text-embedding-3-small" not in ids
    assert "fal/image" not in ids
    openai_entry = next(entry for entry in entries if entry.id == "openai/gpt-4o-mini")
    assert openai_entry.provider == "openai"
    assert openai_entry.mode == "chat"
    assert openai_entry.auth_type == "api_key"
    assert openai_entry.requires_api_key is True
    assert openai_entry.is_available is True
    assert openai_entry.status is None
    assert openai_entry.context_window == 128000


def test_model_catalog_excludes_clear_non_text_models_when_metadata_mode_missing(
    monkeypatch,
) -> None:
    from gitresume.services import model_catalog

    monkeypatch.setattr(
        model_catalog.litellm,
        "model_cost",
        {
            "openai/text-embedding-3-small": {"litellm_provider": "openai"},
            "fal-ai/flux": {"litellm_provider": "fal-ai"},
            "openai/whisper-1": {"litellm_provider": "openai"},
            "dall-e-3": {"litellm_provider": "openai"},
            "openai/gpt-4o-mini-transcribe": {"litellm_provider": "openai"},
            "gpt-4o-mini": {"litellm_provider": "openai"},
            "unknown-provider/mystery-model": {"litellm_provider": "unknown-provider"},
        },
        raising=False,
    )

    entries = model_catalog.LiteLLMModelCatalog().list_models()
    ids = {entry.id for entry in entries}

    assert "openai/text-embedding-3-small" not in ids
    assert "fal-ai/flux" not in ids
    assert "openai/whisper-1" not in ids
    assert "dall-e-3" not in ids
    assert "openai/gpt-4o-mini-transcribe" not in ids
    assert "unknown-provider/mystery-model" not in ids
    assert "gpt-4o-mini" in ids
    assert next(entry for entry in entries if entry.id == "gpt-4o-mini").mode == "chat"


def test_model_catalog_includes_oauth_text_and_responses_models_when_metadata_missing(
    monkeypatch,
) -> None:
    from gitresume.services import model_catalog

    monkeypatch.setattr(model_catalog.litellm, "model_cost", {}, raising=False)

    entries = model_catalog.LiteLLMModelCatalog().list_models()

    by_id = {entry.id: entry for entry in entries}

    assert by_id["github_copilot/gpt-4.1"].supports_oauth is True
    assert by_id["github_copilot/gpt-4.1"].requires_api_key is False
    assert by_id["github_copilot/gpt-4.1"].auth_type == "oauth"
    assert by_id["github_copilot/gpt-4.1"].is_available is False
    assert "Connect github_copilot" in (by_id["github_copilot/gpt-4.1"].status or "")
    assert by_id["chatgpt/codex-mini-latest"].mode == "responses"
    assert by_id["chatgpt/codex-mini-latest"].supports_oauth is True
    assert by_id["chatgpt/codex-mini-latest"].is_available is False
    assert "Connect chatgpt" in (by_id["chatgpt/codex-mini-latest"].status or "")
    assert entries == sorted(entries, key=lambda entry: (entry.provider, entry.id))


def test_model_catalog_marks_litellm_oauth_provider_metadata_as_oauth(
    monkeypatch,
) -> None:
    from gitresume.services import model_catalog
    from gitresume.services.oauth_provider_store import OAuthProviderStatus

    monkeypatch.setattr(
        model_catalog.litellm,
        "model_cost",
        {
            "github_copilot/gpt-5.2": {
                "litellm_provider": "github_copilot",
                "mode": "chat",
            },
            "chatgpt/gpt-5.2": {
                "litellm_provider": "chatgpt",
                "mode": "responses",
            },
        },
        raising=False,
    )
    statuses = {
        "github_copilot": OAuthProviderStatus(provider="github_copilot", connected=True),
        "chatgpt": OAuthProviderStatus(provider="chatgpt", connected=True),
    }

    by_id = {entry.id: entry for entry in model_catalog.LiteLLMModelCatalog(statuses).list_models()}

    assert by_id["github_copilot/gpt-5.2"].auth_type == "oauth"
    assert by_id["github_copilot/gpt-5.2"].is_available is True
    assert by_id["chatgpt/gpt-5.2"].auth_type == "oauth"
    assert by_id["chatgpt/gpt-5.2"].mode == "responses"
    assert by_id["chatgpt/gpt-5.2"].is_available is True
    assert by_id["github_copilot/gpt-5-mini"].auth_type == "oauth"
    assert by_id["github_copilot/gpt-5-mini"].is_available is True


def test_model_catalog_includes_openrouter_free_models_when_metadata_missing(monkeypatch) -> None:
    from gitresume.services import model_catalog

    monkeypatch.setattr(model_catalog.litellm, "model_cost", {}, raising=False)

    by_id = {entry.id: entry for entry in model_catalog.LiteLLMModelCatalog().list_models()}
    free_model = by_id["openrouter/meta-llama/llama-3.1-8b-instruct:free"]

    assert free_model.provider == "openrouter"
    assert free_model.mode == "chat"
    assert free_model.auth_type == "api_key"
    assert free_model.requires_api_key is True
    assert free_model.supports_oauth is False
    assert free_model.is_available is True
    assert "free" in (free_model.status or "").lower()


def test_model_catalog_marks_oauth_models_available_only_when_connected(monkeypatch) -> None:
    from gitresume.services import model_catalog
    from gitresume.services.oauth_provider_store import OAuthProviderStatus

    monkeypatch.setattr(model_catalog.litellm, "model_cost", {}, raising=False)
    statuses = {
        "github_copilot": OAuthProviderStatus(provider="github_copilot", connected=True),
        "chatgpt": OAuthProviderStatus(provider="chatgpt", connected=True),
    }

    by_id = {entry.id: entry for entry in model_catalog.LiteLLMModelCatalog(statuses).list_models()}

    assert by_id["github_copilot/gpt-4.1"].is_available is True
    assert by_id["github_copilot/gpt-4.1"].status is None
    assert by_id["chatgpt/codex-mini-latest"].is_available is True
    assert by_id["chatgpt/codex-mini-latest"].status is None


def test_find_model_entry_uses_oauth_provider_status(monkeypatch) -> None:
    from gitresume.services import model_catalog
    from gitresume.services.oauth_provider_store import OAuthProviderStatus

    monkeypatch.setattr(model_catalog.litellm, "model_cost", {}, raising=False)

    disconnected = model_catalog.find_model_entry("github_copilot/gpt-4.1")
    connected = model_catalog.find_model_entry(
        "github_copilot/gpt-4.1",
        {"github_copilot": OAuthProviderStatus(provider="github_copilot", connected=True)},
    )

    assert disconnected is not None
    assert disconnected.is_available is False
    assert connected is not None
    assert connected.is_available is True


def test_provider_for_model_prefers_litellm_metadata_for_unprefixed_ids(monkeypatch) -> None:
    from gitresume.services import model_catalog

    monkeypatch.setattr(
        model_catalog.litellm,
        "model_cost",
        {"gpt-4o-mini": {"litellm_provider": "openai", "mode": "chat"}},
        raising=False,
    )

    assert model_catalog.provider_for_model("gpt-4o-mini") == "openai"
    assert model_catalog.provider_for_model("anthropic/claude-3-5-sonnet") == "anthropic"


def test_models_endpoint_returns_camel_case_catalog_entries() -> None:
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        redis_url=None,
        settings_encryption_key=None,
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["models"], list)
    first = body["models"][0]
    assert "displayName" in first
    assert "supportsOauth" in first
    assert "requiresApiKey" in first
    assert "authType" in first
    assert "isAvailable" in first
    assert "status" in first
    assert "contextWindow" in first
