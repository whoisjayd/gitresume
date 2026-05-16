import json
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from pydantic import SecretStr

from gitresume.core.config import Settings
from gitresume.core.crypto import StringEncryptor
from gitresume.main import create_app
from gitresume.services.oauth_login_service import (
    OAuthLoginJob,
    OAuthLoginService,
    load_litellm_oauth_credential,
    parse_device_auth_output,
    sanitize_oauth_output,
)

SETTINGS_KEY = "settings encryption passphrase with enough entropy"


def make_client(**overrides: Any) -> TestClient:
    values = {
        "environment": "test",
        "session_secret_key": "test-secret",
        "allowed_hosts": ["testserver"],
        "frontend_origin": "http://testserver",
        "redis_url": "redis://unit-test",
        "settings_encryption_key": SETTINGS_KEY,
    } | overrides
    settings = Settings(**values)
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


def test_device_auth_stdout_parser_extracts_link_and_code_without_tokens() -> None:
    output = "Open https://github.com/login/device and enter code ABCD-1234 token=secret"

    parsed = parse_device_auth_output(sanitize_oauth_output(output))

    assert parsed == {
        "verification_uri": "https://github.com/login/device",
        "user_code": "ABCD-1234",
    }
    assert "secret" not in sanitize_oauth_output(output)


@pytest.mark.asyncio
async def test_oauth_login_job_round_trips_with_api_aliases() -> None:
    redis = FakeRedis(decode_responses=True)
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        redis_url=None,
        settings_encryption_key=None,
    )
    service = OAuthLoginService(redis, settings, store=object(), scope="global")
    now = datetime.now(UTC)
    job = OAuthLoginJob(
        job_id="oauth-login-test",
        provider="github_copilot",
        status="queued",
        status_url="/api/oauth-providers/login-jobs/oauth-login-test",
        message="queued",
        created_at=now,
        updated_at=now,
    )

    await service.save_job(job)

    loaded = await service.get(job.job_id)
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.status_url == job.status_url


def test_litellm_chatgpt_token_file_imports_known_fields(tmp_path) -> None:
    auth_dir = tmp_path / "chatgpt"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text(
        json.dumps(
            {
                "access_token": "chatgpt-access-token",
                "refresh_token": "chatgpt-refresh-token",
                "expires_at": 1893456000,
                "account_id": "acct-chatgpt",
            }
        ),
        encoding="utf-8",
    )

    credential = load_litellm_oauth_credential("chatgpt", tmp_path)

    assert credential.provider == "chatgpt"
    assert credential.access_token.get_secret_value() == "chatgpt-access-token"
    assert credential.refresh_token is not None
    assert credential.refresh_token.get_secret_value() == "chatgpt-refresh-token"
    assert credential.account_label == "acct-chatgpt"
    assert credential.expires_at is not None


def test_litellm_copilot_token_file_imports_known_fields(tmp_path) -> None:
    auth_dir = tmp_path / "github_copilot"
    auth_dir.mkdir()
    (auth_dir / "api-key.json").write_text(
        json.dumps(
            {
                "token": "copilot-token",
                "expires_at": 1893456000,
                "sku": "copilot-pro",
            }
        ),
        encoding="utf-8",
    )

    credential = load_litellm_oauth_credential("github_copilot", tmp_path)

    assert credential.provider == "github_copilot"
    assert credential.access_token.get_secret_value() == "copilot-token"
    assert credential.account_label == "copilot-pro"
    assert credential.expires_at is not None


@pytest.mark.asyncio
async def test_oauth_provider_store_lifecycle_does_not_expose_secret() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))

    connected = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-secret-token"),
            account_label="Octocat",
        ),
    )

    assert connected.provider == "github_copilot"
    assert connected.connected is True
    assert connected.account_label == "Octocat"
    assert "ghu-secret-token" not in repr(connected)
    assert "ghu-secret-token" not in connected.model_dump_json()

    assert await store.get_access_token("global", "github_copilot") == "ghu-secret-token"
    statuses = await store.list_statuses("global", ["github_copilot", "chatgpt"])
    assert [status.provider for status in statuses] == ["github_copilot", "chatgpt"]
    assert statuses[0].connected is True
    assert statuses[1].connected is False
    assert "ghu-secret-token" not in str(statuses)

    assert await store.disconnect("global", "github_copilot") is True
    assert await store.get_access_token("global", "github_copilot") is None


@pytest.mark.asyncio
async def test_oauth_provider_store_adds_accounts_and_rotates_without_secret_leak() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))

    first = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-first-secret"),
            account_label="Work",
        ),
    )
    second = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-second-secret"),
            account_label="Personal",
        ),
    )

    statuses = await store.list_statuses("global", ["github_copilot"])
    github = statuses[0]
    assert github.connected is True
    assert github.executable is True
    assert [account.account_label for account in github.accounts] == ["Work", "Personal"]
    assert first.accounts[0].id != second.accounts[-1].id
    assert "ghu-first-secret" not in github.model_dump_json()
    assert "ghu-second-secret" not in github.model_dump_json()

    assert await store.get_access_token("global", "github_copilot") == "ghu-first-secret"
    assert await store.get_access_token("global", "github_copilot") == "ghu-second-secret"
    assert await store.get_access_token("global", "github_copilot") == "ghu-first-secret"


@pytest.mark.asyncio
async def test_oauth_provider_store_uses_per_account_entries_without_provider_overwrite() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))

    connected = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-secret-token"),
            account_label="Work",
        ),
    )
    account_id = connected.accounts[0].id

    assert await redis.hget("settings:global:oauth-providers", "github_copilot") is None
    account_payload = await redis.hget(
        "settings:global:oauth-provider-accounts:github_copilot",
        account_id,
    )
    assert account_payload is not None
    assert "ghu-secret-token" not in str(account_payload)


@pytest.mark.asyncio
async def test_oauth_provider_store_migrates_legacy_payload_to_stable_account_id() -> None:
    from gitresume.services.oauth_provider_store import RedisOAuthProviderStore

    redis = FakeRedis(decode_responses=True)
    encryptor = StringEncryptor(SETTINGS_KEY)
    legacy_payload = {
        "provider": "github_copilot",
        "encrypted_access_token": encryptor.encrypt("ghu-legacy-secret"),
        "account_label": "Legacy",
        "connection_type": "manual_token",
        "connected_at": "2026-05-15T00:00:00+00:00",
    }
    await redis.hset(
        "settings:global:oauth-providers",
        mapping={"github_copilot": json.dumps(legacy_payload)},
    )
    store = RedisOAuthProviderStore(redis, encryptor)

    first = (await store.list_statuses("global", ["github_copilot"]))[0]
    second = (await store.list_statuses("global", ["github_copilot"]))[0]

    assert first.accounts[0].id == second.accounts[0].id
    assert await redis.hget("settings:global:oauth-providers", "github_copilot") is None
    assert await store.get_access_token("global", "github_copilot") == "ghu-legacy-secret"


@pytest.mark.asyncio
async def test_oauth_provider_store_disconnects_one_account_without_removing_provider() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))
    first = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-first-secret"),
            account_label="Work",
        ),
    )
    await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-second-secret"),
            account_label="Personal",
        ),
    )

    assert await store.disconnect_account("global", "github_copilot", first.accounts[0].id) is True

    github = (await store.list_statuses("global", ["github_copilot"]))[0]
    assert github.connected is True
    assert [account.account_label for account in github.accounts] == ["Personal"]
    assert await store.get_access_token("global", "github_copilot") == "ghu-second-secret"


@pytest.mark.asyncio
async def test_oauth_provider_store_does_not_resurrect_deleted_account_on_selection() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))
    connected = await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-deleted-secret"),
            account_label="Deleted",
        ),
    )

    account_id = connected.accounts[0].id
    assert await store.disconnect_account("global", "github_copilot", account_id) is True

    assert await store.select_access_token("global", "github_copilot") is None
    assert (
        await redis.hget("settings:global:oauth-provider-accounts:github_copilot", account_id)
        is None
    )


@pytest.mark.asyncio
async def test_oauth_provider_store_skips_expired_accounts_without_refresher() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        RedisOAuthProviderStore,
    )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY))
    expired_at = datetime.now(UTC) - timedelta(minutes=1)
    await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-expired-secret"),
            account_label="Expired",
            expires_at=expired_at,
        ),
    )

    github = (await store.list_statuses("global", ["github_copilot"]))[0]
    assert github.connected is True
    assert github.executable is False
    assert github.accounts[0].executable is False
    assert "refresh required" in (github.accounts[0].status or "").lower()
    assert await store.get_access_token("global", "github_copilot") is None


@pytest.mark.asyncio
async def test_oauth_provider_store_refreshes_expired_account_with_injected_refresher() -> None:
    from gitresume.services.oauth_provider_store import (
        OAuthProviderCredentialInput,
        OAuthTokenRefreshResult,
        RedisOAuthProviderStore,
    )

    class FakeRefresher:
        async def refresh(self, *, provider: str, refresh_token: str) -> OAuthTokenRefreshResult:
            assert provider == "github_copilot"
            assert refresh_token == "refresh-secret"
            return OAuthTokenRefreshResult(
                access_token=SecretStr("ghu-refreshed-secret"),
                refresh_token=SecretStr("refresh-secret-2"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    redis = FakeRedis(decode_responses=True)
    store = RedisOAuthProviderStore(redis, StringEncryptor(SETTINGS_KEY), refresher=FakeRefresher())
    await store.connect(
        "global",
        OAuthProviderCredentialInput(
            provider="github_copilot",
            access_token=SecretStr("ghu-expired-secret"),
            refresh_token=SecretStr("refresh-secret"),
            account_label="Refreshable",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    )

    assert await store.get_access_token("global", "github_copilot") == "ghu-refreshed-secret"
    github = (await store.list_statuses("global", ["github_copilot"]))[0]
    assert github.accounts[0].last_refreshed_at is not None
    assert github.accounts[0].expires_at is not None
    assert "ghu-expired-secret" not in github.model_dump_json()
    assert "ghu-refreshed-secret" not in github.model_dump_json()
    assert "refresh-secret" not in github.model_dump_json()


def test_oauth_provider_routes_connect_status_disconnect_without_secret_leak() -> None:
    client = make_client()

    initial = client.get("/api/oauth-providers")
    assert initial.status_code == 200
    github_initial = next(
        item for item in initial.json()["providers"] if item["provider"] == "github_copilot"
    )
    assert github_initial["connected"] is False

    connected = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-secret-token", "accountLabel": "Octocat"},
    )

    assert connected.status_code == 200
    assert connected.json()["connected"] is True
    assert connected.json()["connectionType"] == "manual_token"
    assert "ghu-secret-token" not in connected.text

    status = client.get("/api/oauth-providers")
    assert status.status_code == 200
    body = status.json()
    github = next(item for item in body["providers"] if item["provider"] == "github_copilot")
    assert github["connected"] is True
    assert github["accountLabel"] == "Octocat"
    assert github["accounts"][0]["accountLabel"] == "Octocat"
    assert "ghu-secret-token" not in status.text

    disconnected = client.delete("/api/oauth-providers/github_copilot")
    assert disconnected.status_code == 204
    assert client.get("/api/oauth-providers").json()["providers"][0]["connected"] is False


def test_oauth_provider_routes_add_delete_refresh_accounts_without_secret_leak() -> None:
    client = make_client()

    first = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-first-secret", "accountLabel": "Work"},
    )
    second = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-second-secret", "accountLabel": "Personal"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    status = client.get("/api/oauth-providers")
    github = next(
        item for item in status.json()["providers"] if item["provider"] == "github_copilot"
    )
    account_ids = [account["id"] for account in github["accounts"]]
    assert [account["accountLabel"] for account in github["accounts"]] == ["Work", "Personal"]
    assert "ghu-first-secret" not in status.text
    assert "ghu-second-secret" not in status.text

    refreshed = client.put(
        f"/api/oauth-providers/github_copilot/accounts/{account_ids[0]}",
        json={
            "accessToken": "ghu-refreshed-secret",
            "refreshToken": "refresh-secret",
            "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["accounts"][0]["lastRefreshedAt"] is not None
    assert "ghu-refreshed-secret" not in refreshed.text
    assert "refresh-secret" not in refreshed.text

    deleted = client.delete(f"/api/oauth-providers/github_copilot/accounts/{account_ids[1]}")

    assert deleted.status_code == 204
    github = next(
        item
        for item in client.get("/api/oauth-providers").json()["providers"]
        if item["provider"] == "github_copilot"
    )
    assert [account["id"] for account in github["accounts"]] == [account_ids[0]]


def test_oauth_provider_delete_unknown_account_returns_404() -> None:
    client = make_client()

    response = client.delete("/api/oauth-providers/github_copilot/accounts/missing-account")

    assert response.status_code == 404


def test_oauth_provider_manual_refresh_rejects_empty_or_whitespace_access_token() -> None:
    client = make_client()
    connected = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-secret-token"},
    )
    account_id = connected.json()["accounts"][0]["id"]

    for token in ("", "   "):
        response = client.put(
            f"/api/oauth-providers/github_copilot/accounts/{account_id}",
            json={"accessToken": token},
        )

        assert response.status_code == 422
        assert "accessToken" in response.text or "token" in response.text.lower()


def test_oauth_provider_connect_rejects_empty_or_whitespace_tokens() -> None:
    client = make_client()

    for token in ("", "   "):
        response = client.post(
            "/api/oauth-providers/github_copilot/connect",
            json={"accessToken": token},
        )

        assert response.status_code == 422
        assert "accessToken" in response.text or "token" in response.text.lower()

    status = client.get("/api/oauth-providers")
    github = next(
        item for item in status.json()["providers"] if item["provider"] == "github_copilot"
    )
    assert github["connected"] is False


def test_hosted_oauth_provider_connections_require_github_login_and_are_user_scoped() -> None:
    client = make_client(app_mode="hosted")

    unauthenticated = client.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-secret-token"},
    )
    assert unauthenticated.status_code == 401

    login(client, github_user_id="12345")
    assert (
        client.post(
            "/api/oauth-providers/github_copilot/connect",
            json={"accessToken": "ghu-secret-token"},
        ).status_code
        == 200
    )

    login(client, github_user_id="67890")
    other_user_status = client.get("/api/oauth-providers")
    github = next(
        item
        for item in other_user_status.json()["providers"]
        if item["provider"] == "github_copilot"
    )
    assert github["connected"] is False


def test_oauth_provider_routes_report_disabled_when_encryption_or_redis_missing() -> None:
    no_key = make_client(settings_encryption_key=None)
    response = no_key.get("/api/oauth-providers")
    assert response.status_code == 200
    assert response.json()["providers"][0]["connected"] is False
    assert "disabled" in response.json()["providers"][0]["status"].lower()

    no_redis_settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        redis_url=None,
        settings_encryption_key=SETTINGS_KEY,
    )
    no_redis = TestClient(create_app(no_redis_settings))
    connect = no_redis.post(
        "/api/oauth-providers/github_copilot/connect",
        json={"accessToken": "ghu-secret-token"},
    )
    assert connect.status_code == 503
