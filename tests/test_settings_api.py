import json
from base64 import b64encode
from typing import Any

from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from gitresume.core.config import Settings
from gitresume.main import create_app

SETTINGS_KEY = "settings encryption passphrase with enough entropy"


def make_client(**overrides: Any) -> TestClient:
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        redis_url="redis://unit-test",
        **overrides,
    )
    app = create_app(settings)
    app.state.redis = FakeRedis(decode_responses=True)
    return TestClient(app)


def login(client: TestClient, github_user_id: str = "12345") -> None:
    payload = {
        "is_authenticated": True,
        "github_user": "octocat",
        "github_user_id": github_user_id,
    }
    data = b64encode(json.dumps(payload).encode("utf-8"))
    cookie = TimestampSigner("test-secret").sign(data).decode("utf-8")
    client.cookies.set("session", cookie)


def test_get_settings_reports_disabled_saved_byok_when_encryption_key_missing() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=None)

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "appMode": "self_hosted",
        "allowSavedByok": True,
        "savedKeysEnabled": False,
        "loginRequired": False,
        "guidedAnalysisEnabled": False,
        "contributionAnalysisEnabled": False,
        "contributionAnalysisDefaultDays": 300,
        "defaultModel": None,
        "providerKeys": [],
        "disabledReason": "Saved BYOK is disabled by server configuration.",
    }


def test_get_settings_reports_analysis_flags_when_saved_byok_enabled() -> None:
    client = make_client(
        allow_saved_byok=True,
        settings_encryption_key=SETTINGS_KEY,
        enable_guided_analysis=True,
        enable_contribution_analysis=True,
        contribution_analysis_default_days=180,
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["savedKeysEnabled"] is True
    assert body["guidedAnalysisEnabled"] is True
    assert body["contributionAnalysisEnabled"] is True
    assert body["contributionAnalysisDefaultDays"] == 180


def test_self_hosted_settings_provider_key_lifecycle_does_not_expose_secret() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    created = client.post(
        "/api/settings/provider-keys",
        json={
            "provider": "openai",
            "label": "Work OpenAI",
            "secret": "sk-provider-secret",
            "model": "gpt-4o-mini",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["id"]
    assert body["label"] == "Work OpenAI"
    assert "sk-provider-secret" not in created.text

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["providerKeys"][0]["id"] == body["id"]
    assert "sk-provider-secret" not in settings.text

    deleted = client.delete(f"/api/settings/provider-keys/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/settings").json()["providerKeys"] == []


def test_put_default_model_returns_updated_dashboard_settings() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.put("/api/settings/default-model", json={"model": "gpt-4o-mini"})

    assert response.status_code == 200
    assert response.json()["defaultModel"] == "gpt-4o-mini"


def test_put_default_model_accepts_connected_oauth_model() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)
    connected = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-secret-token"},
    )
    assert connected.status_code == 200

    response = client.put("/api/settings/default-model", json={"model": "github_copilot/gpt-4.1"})

    assert response.status_code == 200
    assert response.json()["defaultModel"] == "github_copilot/gpt-4.1"
    assert "ghu-secret-token" not in response.text


def test_put_default_model_rejects_unavailable_model() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.put("/api/settings/default-model", json={"model": "github_copilot/gpt-4.1"})

    assert response.status_code == 422
    assert "not available" in response.json()["detail"]


def test_put_default_model_rejects_unknown_model() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.put("/api/settings/default-model", json={"model": "unknown/provider-model"})

    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]


def test_put_default_model_rejects_unknown_supported_oauth_provider_model() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.put("/api/settings/default-model", json={"model": "github_copilot/new-model"})

    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]


def test_provider_key_rejects_model_provider_mismatch() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.post(
        "/api/settings/provider-keys",
        json={
            "provider": "gemini",
            "label": "Wrong provider",
            "secret": "secret",
            "model": "gpt-4o-mini",
        },
    )

    assert response.status_code == 422
    assert "does not match model provider" in response.json()["detail"]


def test_provider_key_rejects_unavailable_restricted_model() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.post(
        "/api/settings/provider-keys",
        json={
            "provider": "github_copilot",
            "label": "Copilot",
            "secret": "secret",
            "model": "github_copilot/gpt-4.1",
        },
    )

    assert response.status_code == 422
    assert "not available" in response.json()["detail"]


def test_provider_key_accepts_openrouter_free_model_restriction() -> None:
    client = make_client(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    response = client.post(
        "/api/settings/provider-keys",
        json={
            "provider": "openrouter",
            "label": "OpenRouter Free",
            "secret": "openrouter-secret",
            "model": "openrouter/meta-llama/llama-3.1-8b-instruct:free",
        },
    )

    assert response.status_code == 201
    assert response.json()["provider"] == "openrouter"
    assert response.json()["model"] == "openrouter/meta-llama/llama-3.1-8b-instruct:free"
    assert "openrouter-secret" not in response.text


def test_hosted_saved_keys_require_github_login() -> None:
    client = make_client(
        app_mode="hosted",
        allow_saved_byok=True,
        settings_encryption_key=SETTINGS_KEY,
    )

    get_response = client.get("/api/settings")
    post_response = client.post(
        "/api/settings/provider-keys",
        json={"provider": "openai", "label": "OpenAI", "secret": "sk-secret"},
    )

    assert get_response.status_code == 200
    assert get_response.json()["loginRequired"] is True
    assert get_response.json()["savedKeysEnabled"] is False
    assert post_response.status_code == 401


def test_hosted_saved_keys_are_scoped_to_authenticated_user() -> None:
    client = make_client(
        app_mode="hosted",
        allow_saved_byok=True,
        settings_encryption_key=SETTINGS_KEY,
    )
    login(client, github_user_id="12345")

    created = client.post(
        "/api/settings/provider-keys",
        json={"provider": "gemini", "label": "Gemini", "secret": "gemini-secret"},
    )
    login(client, github_user_id="67890")
    other_user_settings = client.get("/api/settings")

    assert created.status_code == 201
    assert other_user_settings.status_code == 200
    assert other_user_settings.json()["providerKeys"] == []
