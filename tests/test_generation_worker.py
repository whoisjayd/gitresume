from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gitresume.schemas.generation import GenerationState, GenerationStatus
from gitresume.schemas.resume import ResumeDraft


@dataclass(frozen=True)
class FakeCheckout:
    local_path: Path
    owner: str = "example"
    name: str = "project"
    full_name: str = "example/project"
    canonical_url: str = "https://github.com/example/project"


class FakeRedis:
    closed = False

    @classmethod
    def from_url(cls, url: str, decode_responses: bool) -> "FakeRedis":
        assert url == "redis://unit-test"
        assert decode_responses is True
        return cls()

    async def aclose(self) -> None:
        self.closed = True


class FakeStateService:
    instances: list["FakeStateService"] = []

    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.events: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.state = GenerationState(
            generation_id="gen-123",
            status=GenerationStatus.QUEUED,
            repository_url="https://github.com/example/project/",
            job_description="Backend role",
        )
        self.token: str | None = "secret-token"
        self.__class__.instances.append(self)

    async def get_generation(self, generation_id: str) -> GenerationState | None:
        return self.state.model_copy(update={"generation_id": generation_id})

    async def pop_github_token(self, generation_id: str) -> str | None:
        del generation_id
        token = self.token
        self.token = None
        return token

    async def append_event(
        self,
        generation_id: str,
        *,
        event_type: str,
        status: GenerationStatus | None = None,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "generation_id": generation_id,
                "event_type": event_type,
                "status": status,
                "message": message,
                "data": data,
            }
        )

    async def complete_generation(self, generation_id: str, result: dict[str, Any]) -> None:
        self.result = {"generation_id": generation_id, "result": result}
        await self.append_event(
            generation_id,
            event_type="completed",
            status=GenerationStatus.SUCCEEDED,
            message="Generation complete",
            data={"result": result},
        )

    async def fail_generation(self, generation_id: str, error: str) -> None:
        self.error = error
        await self.append_event(
            generation_id,
            event_type="failed",
            status=GenerationStatus.FAILED,
            message=error,
        )


class FakeRepositoryService:
    async def validate_access(
        self, repo_url: str, github_token: str | None = None
    ) -> dict[str, Any]:
        assert repo_url == "https://github.com/example/project/"
        assert github_token in {"secret-token", None}
        return {"success": True}


class FakeCheckoutService:
    instances: list["FakeCheckoutService"] = []

    def __init__(self) -> None:
        self.checkout_result = FakeCheckout(local_path=Path("D:/tmp/fake-checkout"))
        self.cleaned: list[FakeCheckout] = []
        self.__class__.instances.append(self)

    async def checkout(self, repo_url: str, github_token: str | None = None) -> FakeCheckout:
        assert repo_url == "https://github.com/example/project/"
        assert github_token in {"secret-token", None}
        return self.checkout_result

    def cleanup_checkout(self, checkout: FakeCheckout) -> None:
        self.cleaned.append(checkout)


class FakeIngestionService:
    async def build_context(self, repository_path: Path) -> dict[str, Any]:
        assert repository_path == Path("D:/tmp/fake-checkout")
        return {
            "strategy": "unit-test",
            "project_profile": {"language": "Python"},
            "selected_files": ["src/app.py"],
            "context": {"files": []},
        }


class FakeResumeGenerationService:
    def __init__(self, ai_client: object) -> None:
        self.ai_client = ai_client

    async def generate(
        self, *, repo_context: str, job_description: str | None = None
    ) -> ResumeDraft:
        assert '"full_name": "example/project"' in repo_context
        assert '"strategy": "unit-test"' in repo_context
        assert job_description == "Backend role"
        return ResumeDraft(
            project_title="Example Project",
            tech_stack=["Python"],
            bullet_points=["Built API", "Added workers", "Tested flows"],
        )


class FakeLiteLLMResumeClient:
    def __init__(self, settings: object) -> None:
        self.settings = settings


def patch_worker_dependencies(monkeypatch: pytest.MonkeyPatch) -> Any:
    from gitresume.workers import generation_tasks

    FakeStateService.instances.clear()
    FakeCheckoutService.instances.clear()
    monkeypatch.setattr(generation_tasks, "Redis", FakeRedis)
    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", FakeStateService)
    monkeypatch.setattr(generation_tasks, "GitHubRepositoryService", FakeRepositoryService)
    monkeypatch.setattr(generation_tasks, "RepositoryCheckoutService", FakeCheckoutService)
    monkeypatch.setattr(generation_tasks, "RepositoryIngestionService", FakeIngestionService)
    monkeypatch.setattr(generation_tasks, "ResumeGenerationService", FakeResumeGenerationService)
    monkeypatch.setattr(generation_tasks, "LiteLLMResumeClient", FakeLiteLLMResumeClient)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://unit-test"),
    )
    return generation_tasks


@pytest.mark.asyncio
async def test_run_generation_success_emits_stage_events_and_stores_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    await generation_tasks.run_generation.original_func(
        "gen-123",
    )

    state_service = FakeStateService.instances[-1]
    checkout_service = FakeCheckoutService.instances[-1]
    assert [event["event_type"] for event in state_service.events] == [
        "validating",
        "cloning",
        "analyzing",
        "generating",
        "completed",
    ]
    assert [event["status"] for event in state_service.events] == [
        GenerationStatus.VALIDATING,
        GenerationStatus.CLONING,
        GenerationStatus.ANALYZING,
        GenerationStatus.GENERATING,
        GenerationStatus.SUCCEEDED,
    ]
    assert state_service.result == {
        "generation_id": "gen-123",
        "result": {
            "projectTitle": "Example Project",
            "techStack": ["Python"],
            "bulletPoints": ["Built API", "Added workers", "Tested flows"],
            "additionalNotes": "",
            "futurePlans": "",
            "potentialAdvancements": "",
            "interviewQuestions": [],
        },
    }
    assert state_service.token is None
    assert checkout_service.cleaned == [checkout_service.checkout_result]
    assert state_service.redis.closed is True


@pytest.mark.asyncio
async def test_run_generation_failure_emits_failed_event_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class FailingIngestionService:
        async def build_context(self, repository_path: Path) -> dict[str, Any]:
            del repository_path
            raise RuntimeError("analysis failed")

    monkeypatch.setattr(generation_tasks, "RepositoryIngestionService", FailingIngestionService)

    await generation_tasks.run_generation.original_func(
        "gen-456",
    )

    state_service = FakeStateService.instances[-1]
    checkout_service = FakeCheckoutService.instances[-1]
    assert state_service.error == "analysis failed"
    assert state_service.events[-1]["event_type"] == "failed"
    assert state_service.events[-1]["status"] is GenerationStatus.FAILED
    assert checkout_service.cleaned == [checkout_service.checkout_result]
    assert state_service.redis.closed is True
