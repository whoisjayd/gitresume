from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from gitresume.api.dependencies import get_generation_state_service, get_generation_task_dispatcher
from gitresume.core.config import Settings
from gitresume.main import create_app
from gitresume.schemas.generation import (
    GenerationCreateRequest,
    GenerationEvent,
    GenerationState,
    GenerationStatus,
    utc_now,
)
from gitresume.services.settings_store import DashboardSettings, StoredProviderKey

SETTINGS_KEY = "settings encryption passphrase with enough entropy"


def login(client: TestClient, github_user_id: str = "12345") -> None:
    import json
    from base64 import b64encode

    from itsdangerous import TimestampSigner

    payload = {
        "is_authenticated": True,
        "github_user": "octocat",
        "github_user_id": github_user_id,
    }
    data = b64encode(json.dumps(payload).encode("utf-8"))
    cookie = TimestampSigner("test-secret").sign(data).decode("utf-8")
    client.cookies.set("session", cookie)


class FakeGenerationStateService:
    def __init__(self) -> None:
        self.states: dict[str, GenerationState] = {}
        self.events: dict[str, list[GenerationEvent]] = {}
        self.stream_ids: dict[str, list[str]] = {}
        self.stored_tokens: dict[str, str] = {}
        self.stored_provider_api_keys: dict[str, str] = {}
        self.failed: dict[str, str] = {}
        self.fail_create_after_write = False
        self.fail_store_github_token = False
        self.fail_store_provider_api_key = False

    async def create_generation(
        self, generation_id: str, request: GenerationCreateRequest
    ) -> GenerationState:
        state = GenerationState(
            generation_id=generation_id,
            status=GenerationStatus.QUEUED,
            repository_url=str(request.repo_url),
            job_description=request.job_description,
            model=request.model,
            analysis_author=request.analysis_author,
            analysis_days=request.analysis_days,
            provider_key_id=request.provider_key_id,
            provider_key_scope=request.provider_key_scope,
            oauth_provider_scope=request.oauth_provider_scope,
            owner_scope=request.owner_scope,
        )
        self.states[generation_id] = state
        self.events[generation_id] = [
            GenerationEvent(
                generation_id=generation_id,
                event_type="queued",
                status=GenerationStatus.QUEUED,
                message="Generation queued",
                sequence=1,
            )
        ]
        self.stream_ids[generation_id] = ["1-0"]
        if self.fail_create_after_write:
            raise RuntimeError("partial state write failed")
        return state

    async def get_generation(self, generation_id: str) -> GenerationState | None:
        return self.states.get(generation_id)

    async def replay_events(self, generation_id: str) -> list[GenerationEvent]:
        return list(self.events.get(generation_id, []))

    async def replay_events_with_ids(
        self, generation_id: str, *, after_id: str = "0-0"
    ) -> list[tuple[str, GenerationEvent]]:
        events = self.events.get(generation_id, [])
        stream_ids = self.stream_ids.get(generation_id, [])
        return [
            (stream_id, event)
            for stream_id, event in zip(stream_ids, events, strict=True)
            if _redis_stream_id_greater_than(stream_id, after_id)
        ]

    async def latest_event_id(self, generation_id: str) -> str:
        return f"0-{len(self.events.get(generation_id, []))}"

    async def set_task_id(self, generation_id: str, task_id: str) -> None:
        state = self.states[generation_id]
        self.states[generation_id] = state.model_copy(update={"task_id": task_id})

    async def store_github_token(self, generation_id: str, token: str) -> None:
        if self.fail_store_github_token:
            raise RuntimeError("credential store unavailable")
        self.stored_tokens[generation_id] = token

    async def store_provider_api_key(self, generation_id: str, secret: str) -> None:
        if self.fail_store_provider_api_key:
            raise RuntimeError("provider credential store unavailable")
        self.stored_provider_api_keys[generation_id] = secret

    async def delete_github_token(self, generation_id: str) -> None:
        self.stored_tokens.pop(generation_id, None)

    async def delete_provider_api_key(self, generation_id: str) -> None:
        self.stored_provider_api_keys.pop(generation_id, None)

    async def fail_generation(self, generation_id: str, error: str) -> None:
        self.failed[generation_id] = error
        state = self.states[generation_id]
        self.states[generation_id] = state.model_copy(
            update={"status": GenerationStatus.FAILED, "error": error}
        )

    async def stream_events(
        self, generation_id: str, *, after_id: str = "0-0", block_ms: int = 1000
    ) -> AsyncIterator[GenerationEvent]:
        del after_id, block_ms
        for event in self.events.get(generation_id, []):
            yield event

    async def stream_events_with_ids(
        self, generation_id: str, *, after_id: str = "0-0", block_ms: int = 1000
    ) -> AsyncIterator[tuple[str, GenerationEvent]]:
        del block_ms
        events = self.events.get(generation_id, [])
        stream_ids = self.stream_ids.get(generation_id, [])
        for stream_id, event in zip(stream_ids, events, strict=True):
            if _redis_stream_id_greater_than(stream_id, after_id):
                yield stream_id, event


def _redis_stream_id_greater_than(left: str, right: str) -> bool:
    left_time, left_sequence = (int(part) for part in left.split("-", 1))
    right_time, right_sequence = (int(part) for part in right.split("-", 1))
    return (left_time, left_sequence) > (right_time, right_sequence)


class FakeTaskDispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    async def enqueue(self, generation_id: str) -> str:
        self.calls.append(generation_id)
        if self.fail:
            raise RuntimeError("broker unavailable")
        return f"task-{generation_id}"


class FakeSettingsStore:
    def __init__(self) -> None:
        self.dashboard_by_scope: dict[str, DashboardSettings] = {}
        self.keys_by_scope: dict[tuple[str, str], StoredProviderKey] = {}
        self.dashboard_scopes: list[str] = []
        self.key_lookups: list[tuple[str, str]] = []

    async def get_dashboard_settings(self, scope: str) -> DashboardSettings:
        self.dashboard_scopes.append(scope)
        return self.dashboard_by_scope.get(scope, DashboardSettings())

    async def get_provider_key(self, scope: str, key_id: str) -> StoredProviderKey | None:
        self.key_lookups.append((scope, key_id))
        return self.keys_by_scope.get((scope, key_id))


def make_client(
    state_service: FakeGenerationStateService,
    dispatcher: FakeTaskDispatcher,
    **settings_overrides,
) -> TestClient:
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
        settings_encryption_key=SETTINGS_KEY,
        **settings_overrides,
    )
    app = create_app(settings)
    app.dependency_overrides[get_generation_state_service] = lambda: state_service
    app.dependency_overrides[get_generation_task_dispatcher] = lambda: dispatcher
    return TestClient(app)


def patch_settings_store(monkeypatch, store: FakeSettingsStore) -> None:
    from gitresume.api.routes import generations, settings

    monkeypatch.setattr(generations, "_settings_store", lambda request, settings: store)
    monkeypatch.setattr(settings, "_settings_store", lambda request, settings: store)


def test_get_settings_exposes_analysis_capabilities_when_enabled(monkeypatch) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
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


def test_get_settings_exposes_analysis_capabilities_when_saved_settings_disabled() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=False,
        enable_guided_analysis=True,
        enable_contribution_analysis=True,
        contribution_analysis_default_days=120,
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["savedKeysEnabled"] is False
    assert body["guidedAnalysisEnabled"] is True
    assert body["contributionAnalysisEnabled"] is True
    assert body["contributionAnalysisDefaultDays"] == 120


def test_post_generation_enqueues_job_and_returns_urls() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "jobDescription": "Backend role",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["generationId"]
    assert body["statusUrl"] == f"/api/generations/{body['generationId']}"
    assert body["eventsUrl"] == f"/api/generations/{body['generationId']}/events"
    assert body["redirectPath"] == f"/generations/{body['generationId']}"
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0] == body["generationId"]


def test_post_generation_rejects_author_scope_when_contribution_analysis_disabled() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher, enable_contribution_analysis=False)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "analysisAuthor": "Jaydeep Solanki",
            "analysisDays": 300,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Contribution analysis is not enabled."
    assert dispatcher.calls == []


def test_post_generation_persists_author_scope_when_contribution_analysis_enabled() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(
        state_service,
        dispatcher,
        enable_guided_analysis=True,
        enable_contribution_analysis=True,
    )

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "analysisAuthor": "Jaydeep Solanki",
            "analysisDays": 300,
        },
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    assert state_service.states[generation_id].analysis_author == "Jaydeep Solanki"
    assert state_service.states[generation_id].analysis_days == 300


def test_post_generation_persists_self_hosted_dashboard_default_model(monkeypatch) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.dashboard_by_scope["global"] = DashboardSettings(default_model="openai/gpt-4o-mini")
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
        ai_model="gemini/gemini-1.5-flash",
    )

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project"},
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    assert state_service.states[generation_id].model == "openai/gpt-4o-mini"
    assert dispatcher.calls == [generation_id]
    assert store.dashboard_scopes == ["global"]


def test_post_generation_hosted_dashboard_default_uses_authenticated_user_scope(
    monkeypatch,
) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.dashboard_by_scope["user:12345"] = DashboardSettings(default_model="openai/gpt-4o-mini")
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        app_mode="hosted",
        allow_saved_byok=True,
        ai_model="gemini/gemini-1.5-flash",
    )
    login(client, github_user_id="12345")

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project"},
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    assert state_service.states[generation_id].model == "openai/gpt-4o-mini"
    assert state_service.states[generation_id].owner_scope == "user:12345"
    assert store.dashboard_scopes == ["user:12345"]


def test_post_generation_ignores_client_supplied_internal_scopes() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "owner_scope": "user:evil",
            "provider_key_scope": "user:evil",
            "oauth_provider_scope": "user:evil",
        },
    )

    assert response.status_code == 202
    state = state_service.states[response.json()["generationId"]]
    assert state.owner_scope is None
    assert state.provider_key_scope is None
    assert state.oauth_provider_scope is None


def test_hosted_post_generation_overwrites_client_supplied_owner_scope() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher, app_mode="hosted")
    login(client, github_user_id="12345")

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "owner_scope": "user:evil",
        },
    )

    assert response.status_code == 202
    assert state_service.states[response.json()["generationId"]].owner_scope == "user:12345"


def test_get_generation_status_returns_current_state() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    created = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project"},
    ).json()

    response = client.get(created["statusUrl"])

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["repositoryUrl"] == "https://github.com/example/project/"


def test_post_generation_accepts_model_and_provider_key_without_exposing_key_id(
    monkeypatch,
) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.keys_by_scope[("global", "key-123")] = StoredProviderKey(
        id="key-123",
        provider="openai",
        label="OpenAI",
        model=None,
        created_at=utc_now(),
    )
    patch_settings_store(monkeypatch, store)
    client = make_client(state_service, dispatcher, allow_saved_byok=True)

    created = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "openai/gpt-4o-mini",
            "providerKeyId": "key-123",
        },
    ).json()

    response = client.get(created["statusUrl"])

    generation_id = created["generationId"]
    assert dispatcher.calls == [generation_id]
    assert state_service.states[generation_id].provider_key_id == "key-123"
    assert response.json()["model"] == "openai/gpt-4o-mini"
    assert "providerKeyId" not in response.json()


def test_post_generation_rejects_unknown_provider_key_before_state_creation(monkeypatch) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
        ai_model="openai/gpt-4o-mini",
    )

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "providerKeyId": "missing-key",
        },
    )

    assert response.status_code == 422
    assert "provider key" in response.json()["detail"].lower()
    assert state_service.states == {}
    assert dispatcher.calls == []
    assert store.key_lookups == [("global", "missing-key")]


def test_post_generation_rejects_provider_key_provider_mismatch_before_enqueue(
    monkeypatch,
) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.keys_by_scope[("global", "key-123")] = StoredProviderKey(
        id="key-123",
        provider="gemini",
        label="Gemini",
        model=None,
        created_at=utc_now(),
    )
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
        ai_model="openai/gpt-4o-mini",
    )

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "providerKeyId": "key-123",
        },
    )

    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_rejects_provider_key_model_mismatch_before_enqueue(
    monkeypatch,
) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.keys_by_scope[("global", "key-123")] = StoredProviderKey(
        id="key-123",
        provider="openai",
        label="OpenAI",
        model="openai/gpt-4o-mini",
        created_at=utc_now(),
    )
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
        ai_model="openai/gpt-4.1-mini",
    )

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "providerKeyId": "key-123",
        },
    )

    assert response.status_code == 422
    assert "is restricted to model" in response.json()["detail"]
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_rejects_inactive_provider_key_before_enqueue(monkeypatch) -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    store = FakeSettingsStore()
    store.keys_by_scope[("global", "key-123")] = StoredProviderKey(
        id="key-123",
        provider="openai",
        label="OpenAI",
        model=None,
        created_at=utc_now(),
        is_active=False,
    )
    patch_settings_store(monkeypatch, store)
    client = make_client(
        state_service,
        dispatcher,
        allow_saved_byok=True,
        ai_model="openai/gpt-4o-mini",
    )

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "providerKeyId": "key-123",
        },
    )

    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_persists_task_id_on_status() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    created = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project"},
    ).json()

    response = client.get(created["statusUrl"])

    assert response.status_code == 200
    assert response.json()["taskId"] == f"task-{created['generationId']}"


def test_post_generation_does_not_send_token_to_dispatcher_payload() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "secret-token"},
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    assert dispatcher.calls == [generation_id]
    assert state_service.stored_tokens == {generation_id: "secret-token"}
    assert "secret-token" not in response.text


def test_post_generation_stores_ephemeral_provider_api_key_outside_state_and_responses() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "openai/gpt-4o-mini",
            "providerApiKey": "sk-provider-secret",
        },
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    status_response = client.get(response.json()["statusUrl"])
    assert state_service.stored_provider_api_keys == {generation_id: "sk-provider-secret"}
    assert "sk-provider-secret" not in response.text
    assert "sk-provider-secret" not in status_response.text
    assert "sk-provider-secret" not in repr(state_service.states[generation_id])


def test_post_generation_deletes_ephemeral_provider_api_key_when_enqueue_fails() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    dispatcher.fail = True
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "providerApiKey": "sk-provider-secret",
        },
    )

    assert response.status_code == 503
    assert state_service.stored_provider_api_keys == {}


def test_post_generation_cleans_up_and_fails_state_when_github_token_storage_fails() -> None:
    state_service = FakeGenerationStateService()
    state_service.fail_store_github_token = True
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "secret-token"},
    )

    assert response.status_code == 503
    generation_id = next(iter(state_service.states))
    assert state_service.states[generation_id].status is GenerationStatus.FAILED
    assert state_service.failed[generation_id] == "Failed to enqueue generation job."
    assert state_service.stored_tokens == {}
    assert state_service.stored_provider_api_keys == {}
    assert dispatcher.calls == []


def test_post_generation_cleans_up_and_fails_partial_state_when_create_raises() -> None:
    state_service = FakeGenerationStateService()
    state_service.fail_create_after_write = True
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "secret-token"},
    )

    assert response.status_code == 503
    generation_id = next(iter(state_service.states))
    assert state_service.states[generation_id].status is GenerationStatus.FAILED
    assert state_service.failed[generation_id] == "Failed to enqueue generation job."
    assert state_service.stored_tokens == {}
    assert state_service.stored_provider_api_keys == {}
    assert dispatcher.calls == []


def test_post_generation_cleans_up_and_fails_state_when_provider_key_storage_fails() -> None:
    state_service = FakeGenerationStateService()
    state_service.fail_store_provider_api_key = True
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "githubToken": "secret-token",
            "providerApiKey": "provider-secret",
        },
    )

    assert response.status_code == 503
    generation_id = next(iter(state_service.states))
    assert state_service.states[generation_id].status is GenerationStatus.FAILED
    assert state_service.failed[generation_id] == "Failed to enqueue generation job."
    assert state_service.stored_tokens == {}
    assert state_service.stored_provider_api_keys == {}
    assert dispatcher.calls == []


def test_generation_create_request_github_token_is_secret_safe() -> None:
    request = GenerationCreateRequest(
        repo_url="https://github.com/example/project",
        github_token="secret-token",
    )

    assert isinstance(request.github_token, SecretStr)
    assert "secret-token" not in repr(request)
    assert "secret-token" not in str(request.model_dump())
    assert "secret-token" not in request.model_dump_json()


def test_post_generation_marks_state_failed_when_enqueue_fails() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    dispatcher.fail = True
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "secret-token"},
    )

    assert response.status_code == 503
    generation_id = dispatcher.calls[0]
    assert state_service.states[generation_id].status is GenerationStatus.FAILED
    assert state_service.failed[generation_id] == "Failed to enqueue generation job."
    assert generation_id not in state_service.stored_tokens


def test_post_generation_rejects_unavailable_oauth_model_before_state_creation() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "github_copilot/gpt-4.1",
        },
    )

    assert response.status_code == 422
    assert "not available" in response.json()["detail"]
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_accepts_connected_oauth_model_and_stores_oauth_scope(monkeypatch) -> None:
    from gitresume.api.routes import generations
    from gitresume.services.oauth_provider_store import OAuthProviderStatus

    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    async def fake_statuses(request):
        del request
        return {"github_copilot": OAuthProviderStatus(provider="github_copilot", connected=True)}

    monkeypatch.setattr(generations, "_oauth_provider_statuses", fake_statuses)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "github_copilot/gpt-4.1",
        },
    )

    assert response.status_code == 202
    generation_id = response.json()["generationId"]
    assert dispatcher.calls == [generation_id]
    assert state_service.states[generation_id].model == "github_copilot/gpt-4.1"
    assert state_service.states[generation_id].oauth_provider_scope == "global"
    assert "oauth" not in response.text.lower()


def test_post_generation_rejects_disconnected_oauth_model_even_when_unknown_to_static_catalog() -> (
    None
):
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "chatgpt/codex-mini-latest",
        },
    )

    assert response.status_code == 422
    assert "Connect chatgpt" in response.json()["detail"]
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_rejects_unknown_oauth_provider_model_before_state_creation() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={
            "repoUrl": "https://github.com/example/project",
            "model": "github_copilot/new-model",
        },
    )

    assert response.status_code == 422
    assert "Unknown model" in response.json()["detail"]
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_post_generation_rejects_userinfo_repository_url_before_state_creation() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

    response = client.post(
        "/api/generations",
        json={"repoUrl": "https://token@github.com/example/project"},
    )

    assert response.status_code == 422
    assert state_service.states == {}
    assert dispatcher.calls == []


def test_sse_endpoint_streams_seeded_terminal_event_without_hanging() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)
    generation_id = "gen-terminal"
    state_service.states[generation_id] = GenerationState(
        generation_id=generation_id,
        status=GenerationStatus.SUCCEEDED,
        repository_url="https://github.com/example/project",
    )
    state_service.events[generation_id] = [
        GenerationEvent(
            generation_id=generation_id,
            event_type="completed",
            status=GenerationStatus.SUCCEEDED,
            message="Generation complete",
            sequence=1,
        )
    ]
    state_service.stream_ids[generation_id] = ["42-0"]

    with client.stream("GET", f"/api/generations/{generation_id}/events") as response:
        body = next(response.iter_text())

    assert response.status_code == 200
    assert "id: 42-0" in body
    assert "event: completed" in body
    assert '"status":"succeeded"' in body


def test_sse_endpoint_replays_only_events_after_last_event_id() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)
    generation_id = "gen-replay"
    state_service.states[generation_id] = GenerationState(
        generation_id=generation_id,
        status=GenerationStatus.SUCCEEDED,
        repository_url="https://github.com/example/project",
    )
    state_service.events[generation_id] = [
        GenerationEvent(
            generation_id=generation_id,
            event_type="queued",
            status=GenerationStatus.QUEUED,
            message="Generation queued",
            sequence=1,
        ),
        GenerationEvent(
            generation_id=generation_id,
            event_type="completed",
            status=GenerationStatus.SUCCEEDED,
            message="Generation complete",
            sequence=2,
        ),
    ]
    state_service.stream_ids[generation_id] = ["1-0", "2-0"]

    with client.stream(
        "GET",
        f"/api/generations/{generation_id}/events",
        headers={"Last-Event-ID": "1-0"},
    ) as response:
        body = next(response.iter_text())

    assert response.status_code == 200
    assert "id: 1-0" not in body
    assert "event: queued" not in body
    assert "id: 2-0" in body
    assert "event: completed" in body


def test_sse_endpoint_rejects_malformed_last_event_id() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)
    generation_id = "gen-bad-id"
    state_service.states[generation_id] = GenerationState(
        generation_id=generation_id,
        status=GenerationStatus.QUEUED,
        repository_url="https://github.com/example/project",
    )

    response = client.get(
        f"/api/generations/{generation_id}/events",
        headers={"Last-Event-ID": "not-a-stream-id"},
    )

    assert response.status_code == 400


def test_hosted_generation_status_requires_authenticated_owner() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher, app_mode="hosted")
    generation_id = "gen-owned"
    state_service.states[generation_id] = GenerationState(
        generation_id=generation_id,
        status=GenerationStatus.QUEUED,
        repository_url="https://github.com/example/project",
        owner_scope="user:12345",
    )

    anonymous_response = client.get(f"/api/generations/{generation_id}")
    login(client, github_user_id="67890")
    other_user_response = client.get(f"/api/generations/{generation_id}")
    login(client, github_user_id="12345")
    owner_response = client.get(f"/api/generations/{generation_id}")

    assert anonymous_response.status_code == 401
    assert other_user_response.status_code == 404
    assert owner_response.status_code == 200


def test_hosted_generation_events_require_authenticated_owner() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher, app_mode="hosted")
    generation_id = "gen-owned-events"
    state_service.states[generation_id] = GenerationState(
        generation_id=generation_id,
        status=GenerationStatus.SUCCEEDED,
        repository_url="https://github.com/example/project",
        owner_scope="user:12345",
    )
    state_service.events[generation_id] = [
        GenerationEvent(
            generation_id=generation_id,
            event_type="completed",
            status=GenerationStatus.SUCCEEDED,
            message="Generation complete",
            sequence=1,
        )
    ]
    state_service.stream_ids[generation_id] = ["1-0"]

    anonymous_response = client.get(f"/api/generations/{generation_id}/events")
    login(client, github_user_id="67890")
    other_user_response = client.get(f"/api/generations/{generation_id}/events")
    login(client, github_user_id="12345")
    with client.stream("GET", f"/api/generations/{generation_id}/events") as owner_response:
        body = next(owner_response.iter_text())

    assert anonymous_response.status_code == 401
    assert other_user_response.status_code == 404
    assert owner_response.status_code == 200
    assert "event: completed" in body
