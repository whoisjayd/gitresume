import base64
import json
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from gitresume.core.config import Settings
from gitresume.main import create_app


def make_client(**overrides: Any) -> TestClient:
    settings_values = {
        "environment": "test",
        "session_secret_key": "test-secret",
        "allowed_hosts": ["testserver"],
        "frontend_origin": "http://testserver",
        "redis_url": None,
        "settings_encryption_key": None,
        "github_client_secret": None,
        "callback_url": None,
        "session_cookie_https_only": None,
        **overrides,
    }
    settings = Settings(**settings_values)
    return TestClient(create_app(settings))


def make_production_client(**overrides: Any) -> TestClient:
    settings = Settings(
        environment="production",
        session_secret_key="production-secret-with-at-least-32-chars",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
        redis_url=None,
        settings_encryption_key=None,
        session_cookie_https_only=True,
        **overrides,
    )
    return TestClient(create_app(settings))


def session_cookie_payload(client: TestClient) -> dict[str, Any]:
    cookie = client.cookies.get("session")
    assert cookie is not None
    encoded = unquote(cookie).split(".", maxsplit=1)[0]
    padded = encoded + "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode())


def install_fake_github_client(
    monkeypatch,
    token: str | None = "gho_secret_token",
    token_payload: Any | None = None,
    user_payload: Any | None = None,
    token_exception: Exception | None = None,
    user_exception: Exception | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.payload

    class FakeAsyncClient:
        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            calls.append(("POST", url, kwargs))
            if token_exception is not None:
                raise token_exception
            payload = token_payload
            if payload is None:
                payload = {"access_token": token} if token is not None else {}
            return FakeResponse(payload)

        async def get(self, url: str, **kwargs: Any) -> FakeResponse:
            calls.append(("GET", url, kwargs))
            if user_exception is not None:
                raise user_exception
            return FakeResponse(user_payload or {"login": "octocat", "id": 12345})

    monkeypatch.setattr("gitresume.api.routes.session.httpx.AsyncClient", FakeAsyncClient)
    return calls


def complete_login(client: TestClient) -> None:
    login_response = client.get("/api/session/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )


def start_login(client: TestClient, next_path: str | None = None) -> str:
    params = {"next": next_path} if next_path is not None else None
    login_response = client.get("/api/session/login", params=params, follow_redirects=False)
    assert login_response.status_code == 307
    return parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]


def assert_oauth_state_consumed(client: TestClient) -> None:
    cookie = client.cookies.get("session")
    if cookie is None:
        return
    session_data = session_cookie_payload(client)
    assert "github_oauth_state" not in session_data
    assert "post_login_redirect" not in session_data


def make_http_status_error(message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://github.example.test")
    response = httpx.Response(500, request=request)
    return httpx.HTTPStatusError(message, request=request, response=response)


def test_session_response_reports_self_hosted_without_login_requirement() -> None:
    client = make_client(app_mode="self_hosted")

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json() == {
        "isAuthenticated": False,
        "githubUser": None,
        "githubUserId": None,
        "appMode": "self_hosted",
        "loginRequired": False,
    }


def test_session_response_reports_hosted_loginRequired_when_logged_out() -> None:
    client = make_client(app_mode="hosted")

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json()["loginRequired"] is True
    assert response.json()["appMode"] == "hosted"


def test_login_redirects_to_github_authorize_with_state_in_session() -> None:
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )

    response = client.get("/api/session/login", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://github.com/login/oauth/authorize"
    )
    assert params["client_id"] == ["client-id"]
    assert params["redirect_uri"] == ["https://example.com/api/session/callback"]
    assert params["scope"] == ["read:user"]
    assert params["state"] == [session_cookie_payload(client)["github_oauth_state"]]


def test_production_session_cookie_is_secure_when_login_writes_state() -> None:
    client = make_production_client()

    response = client.get("/api/session/login", follow_redirects=False)

    assert response.status_code == 307
    assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    "weak_secret",
    [
        "change-me-in-production",
        "change-me",
        "",
        "   ",
        "short-secret",
    ],
)
def test_production_rejects_weak_or_placeholder_session_secret(weak_secret: str) -> None:
    with pytest.raises(ValueError, match="session_secret_key"):
        Settings(environment="production", session_secret_key=weak_secret)


def test_login_returns_service_unavailable_when_oauth_config_missing() -> None:
    client = make_client(github_client_id="client-id")

    response = client.get("/api/session/login", follow_redirects=False)

    assert response.status_code == 503
    assert "GitHub OAuth is not configured" in response.json()["detail"]


def test_callback_rejects_invalid_state_without_authenticating() -> None:
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    client.get("/api/session/login", follow_redirects=False)

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": "wrong-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert client.get("/api/session").json()["isAuthenticated"] is False


def test_callback_rejects_missing_state_without_authenticating() -> None:
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    client.get("/api/session/login", follow_redirects=False)

    response = client.get(
        "/api/session/callback",
        params={"code": "code"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert client.get("/api/session").json()["isAuthenticated"] is False


def test_callback_invalid_state_clears_existing_authentication(monkeypatch) -> None:
    install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    complete_login(client)
    assert client.get("/api/session").json()["isAuthenticated"] is True
    client.get("/api/session/login", follow_redirects=False)

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": "wrong-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert client.get("/api/session").json() == {
        "isAuthenticated": False,
        "githubUser": None,
        "githubUserId": None,
        "appMode": "self_hosted",
        "loginRequired": False,
    }


def test_callback_valid_state_missing_code_consumes_oauth_state_and_redirect(monkeypatch) -> None:
    install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"state": state},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing GitHub OAuth code."
    assert_oauth_state_consumed(client)


def test_callback_exchanges_code_fetches_user_and_does_not_store_token(monkeypatch) -> None:
    calls = install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    login_response = client.get("/api/session/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/"
    assert calls == [
        (
            "POST",
            "https://github.com/login/oauth/access_token",
            {
                "data": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "code": "code",
                    "redirect_uri": "https://example.com/api/session/callback",
                },
                "headers": {"Accept": "application/json"},
            },
        ),
        (
            "GET",
            "https://api.github.com/user",
            {"headers": {"Authorization": "Bearer gho_secret_token"}},
        ),
    ]
    assert client.get("/api/session").json() == {
        "isAuthenticated": True,
        "githubUser": "octocat",
        "githubUserId": "12345",
        "appMode": "self_hosted",
        "loginRequired": False,
    }
    session_data = session_cookie_payload(client)
    assert session_data == {
        "is_authenticated": True,
        "github_user": "octocat",
        "github_user_id": "12345",
    }
    assert "gho_secret_token" not in unquote(client.cookies["session"])


def test_callback_token_exchange_missing_access_token_returns_502_and_consumes_state(
    monkeypatch,
) -> None:
    install_fake_github_client(monkeypatch, token=None)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "GitHub OAuth token exchange failed."
    assert_oauth_state_consumed(client)


@pytest.mark.parametrize("token_payload", [["not", "an", "object"], "not-an-object"])
def test_callback_token_exchange_non_object_json_returns_sanitized_502(
    monkeypatch, token_payload: Any
) -> None:
    install_fake_github_client(monkeypatch, token_payload=token_payload)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "GitHub OAuth token exchange failed."
    assert_oauth_state_consumed(client)


@pytest.mark.parametrize(
    "token_exception",
    [
        make_http_status_error("token status failed with secret gho_secret_token"),
        httpx.RequestError("network failed with secret gho_secret_token"),
    ],
)
def test_callback_token_exchange_failure_returns_sanitized_502_and_consumes_state(
    monkeypatch, token_exception: Exception
) -> None:
    install_fake_github_client(monkeypatch, token_exception=token_exception)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "GitHub OAuth token exchange failed."
    assert "gho_secret_token" not in response.text
    assert_oauth_state_consumed(client)


def test_callback_user_fetch_failure_returns_sanitized_502(monkeypatch) -> None:
    install_fake_github_client(
        monkeypatch,
        user_exception=make_http_status_error("user lookup failed with secret gho_secret_token"),
    )
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "GitHub user lookup failed."
    assert "gho_secret_token" not in response.text
    assert_oauth_state_consumed(client)


@pytest.mark.parametrize("user_payload", [["not", "an", "object"], "not-an-object"])
def test_callback_user_fetch_non_object_json_returns_sanitized_502(
    monkeypatch, user_payload: Any
) -> None:
    install_fake_github_client(monkeypatch, user_payload=user_payload)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    state = start_login(client, next_path="/dashboard")

    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "GitHub user lookup failed."
    assert_oauth_state_consumed(client)


def test_login_stores_safe_post_login_redirect_and_callback_uses_it(monkeypatch) -> None:
    install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )

    state = start_login(client, next_path="/dashboard")

    assert session_cookie_payload(client)["post_login_redirect"] == "/dashboard"
    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


@pytest.mark.parametrize("unsafe_next", ["//evil.example", "https://evil.example"])
def test_login_ignores_unsafe_post_login_redirects(monkeypatch, unsafe_next: str) -> None:
    install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )

    state = start_login(client, next_path=unsafe_next)

    assert "post_login_redirect" not in session_cookie_payload(client)
    response = client.get(
        "/api/session/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/"


def test_logout_clears_authentication_session(monkeypatch) -> None:
    install_fake_github_client(monkeypatch)
    client = make_client(
        github_client_id="client-id",
        github_client_secret="client-secret",
        callback_url="https://example.com/api/session/callback",
    )
    complete_login(client)
    assert client.get("/api/session").json()["isAuthenticated"] is True

    response = client.post("/api/session/logout")

    assert response.status_code == 200
    assert response.json() == {
        "isAuthenticated": False,
        "githubUser": None,
        "githubUserId": None,
        "appMode": "self_hosted",
        "loginRequired": False,
    }
    assert client.cookies.get("session") is None
