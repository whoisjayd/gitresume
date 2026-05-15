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
)


class FakeGenerationStateService:
    def __init__(self) -> None:
        self.states: dict[str, GenerationState] = {}
        self.events: dict[str, list[GenerationEvent]] = {}
        self.stream_ids: dict[str, list[str]] = {}
        self.stored_tokens: dict[str, str] = {}
        self.failed: dict[str, str] = {}

    async def create_generation(
        self, generation_id: str, request: GenerationCreateRequest
    ) -> GenerationState:
        state = GenerationState(
            generation_id=generation_id,
            status=GenerationStatus.QUEUED,
            repository_url=str(request.repo_url),
            job_description=request.job_description,
            model=request.model,
            provider_key_id=request.provider_key_id,
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
            if stream_id > after_id
        ]

    async def latest_event_id(self, generation_id: str) -> str:
        return f"0-{len(self.events.get(generation_id, []))}"

    async def set_task_id(self, generation_id: str, task_id: str) -> None:
        state = self.states[generation_id]
        self.states[generation_id] = state.model_copy(update={"task_id": task_id})

    async def store_github_token(self, generation_id: str, token: str) -> None:
        self.stored_tokens[generation_id] = token

    async def delete_github_token(self, generation_id: str) -> None:
        self.stored_tokens.pop(generation_id, None)

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
            if stream_id > after_id:
                yield stream_id, event


class FakeTaskDispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    async def enqueue(self, generation_id: str) -> str:
        self.calls.append(generation_id)
        if self.fail:
            raise RuntimeError("broker unavailable")
        return f"task-{generation_id}"


def make_client(
    state_service: FakeGenerationStateService, dispatcher: FakeTaskDispatcher
) -> TestClient:
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
    )
    app = create_app(settings)
    app.dependency_overrides[get_generation_state_service] = lambda: state_service
    app.dependency_overrides[get_generation_task_dispatcher] = lambda: dispatcher
    return TestClient(app)


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


def test_post_generation_accepts_model_and_provider_key_without_exposing_key_id() -> None:
    state_service = FakeGenerationStateService()
    dispatcher = FakeTaskDispatcher()
    client = make_client(state_service, dispatcher)

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
