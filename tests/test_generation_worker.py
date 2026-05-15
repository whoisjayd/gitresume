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
        self.provider_api_key: str | None = None
        self.__class__.instances.append(self)

    async def get_generation(self, generation_id: str) -> GenerationState | None:
        return self.state.model_copy(update={"generation_id": generation_id})

    async def pop_github_token(self, generation_id: str) -> str | None:
        del generation_id
        token = self.token
        self.token = None
        return token

    async def pop_provider_api_key(self, generation_id: str) -> str | None:
        del generation_id
        secret = self.provider_api_key
        self.provider_api_key = None
        return secret

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
    fail_with_message: str | None = None

    async def validate_access(
        self, repo_url: str, github_token: str | None = None
    ) -> dict[str, Any]:
        assert repo_url == "https://github.com/example/project/"
        assert github_token in {"secret-token", None}
        if self.fail_with_message is not None:
            raise RuntimeError(self.fail_with_message)
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
    calls: list[dict[str, Any]] = []

    def __init__(self, ai_client: object) -> None:
        self.ai_client = ai_client

    async def generate(
        self,
        *,
        repo_context: str,
        job_description: str | None = None,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
    ) -> ResumeDraft:
        assert '"full_name": "example/project"' in repo_context
        assert '"strategy": "unit-test"' in repo_context
        assert job_description == "Backend role"
        self.calls.append(
            {
                "model": model,
                "provider_api_key": provider_api_key,
                "model_mode": model_mode,
                "ai_client": self.ai_client,
            }
        )
        return ResumeDraft(
            project_title="Example Project",
            tech_stack=["Python"],
            bullet_points=["Built API", "Added workers", "Tested flows"],
        )


class FakeLiteLLMResumeClient:
    def __init__(self, settings: object) -> None:
        self.settings = settings


class FakeSecret:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_secret_value(self) -> str:
        return self.value


class FakeStringEncryptor:
    def __init__(self, key: str) -> None:
        self.key = key


class FakeSettingsStore:
    def __init__(self, redis: object, encryptor: object) -> None:
        self.redis = redis
        self.encryptor = encryptor


def patch_worker_dependencies(monkeypatch: pytest.MonkeyPatch) -> Any:
    from gitresume.workers import generation_tasks

    FakeStateService.instances.clear()
    FakeCheckoutService.instances.clear()
    FakeRepositoryService.fail_with_message = None
    FakeResumeGenerationService.calls.clear()
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
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
        ),
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
async def test_run_generation_uses_selected_model_without_secret_in_state_or_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class ModelStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(update={"model": "openai/gpt-4o-mini"})

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", ModelStateService)

    await generation_tasks.run_generation.original_func("gen-model")

    assert FakeResumeGenerationService.calls[-1]["model"] == "openai/gpt-4o-mini"
    state_service = ModelStateService.instances[-1]
    assert "provider_api_key" not in str(state_service.events)


@pytest.mark.asyncio
async def test_run_generation_rotates_saved_key_for_selected_model_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class ModelStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(update={"model": "openai/gpt-4o-mini"})

    class FakeStringEncryptor:
        def __init__(self, key: str) -> None:
            self.key = key

    class FakeSettingsStore:
        def __init__(self, redis: object, encryptor: object) -> None:
            self.redis = redis
            self.encryptor = encryptor

    class FakeSelectedKey:
        secret = FakeSecret("sk-rotated")

    class FakeSelector:
        calls: list[dict[str, str | None]] = []

        def __init__(self, redis: object, settings_store: object) -> None:
            self.redis = redis
            self.settings_store = settings_store

        async def select(
            self,
            *,
            scope: str,
            provider: str,
            model: str | None = None,
            provider_key_id: str | None = None,
        ) -> FakeSelectedKey:
            self.calls.append(
                {
                    "scope": scope,
                    "provider": provider,
                    "model": model,
                    "provider_key_id": provider_key_id,
                }
            )
            return FakeSelectedKey()

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", ModelStateService)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "RedisSettingsStore", FakeSettingsStore)
    monkeypatch.setattr(generation_tasks, "RedisProviderKeySelector", FakeSelector)
    monkeypatch.setattr(generation_tasks, "provider_for_model", lambda model: "openai")
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=True,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-model")

    assert FakeSelector.calls == [
        {
            "scope": "global",
            "provider": "openai",
            "model": "openai/gpt-4o-mini",
            "provider_key_id": None,
        }
    ]
    assert FakeResumeGenerationService.calls[-1]["provider_api_key"] == "sk-rotated"


@pytest.mark.asyncio
async def test_run_generation_redacts_selected_provider_secret_from_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class KeyedStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={"model": "openai/gpt-4o-mini", "provider_key_id": "key-123"}
            )

    class FakeSelectedKey:
        secret = FakeSecret("sk-sensitive")

    class FakeSelector:
        def __init__(self, redis: object, settings_store: object) -> None:
            del redis, settings_store

        async def select(self, **kwargs: object) -> FakeSelectedKey:
            del kwargs
            return FakeSelectedKey()

    class LeakyResumeGenerationService(FakeResumeGenerationService):
        async def generate(self, **kwargs: object) -> ResumeDraft:
            raise RuntimeError("provider rejected github=secret-token api_key=sk-sensitive")

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", KeyedStateService)
    monkeypatch.setattr(generation_tasks, "RedisProviderKeySelector", FakeSelector)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "RedisSettingsStore", FakeSettingsStore)
    monkeypatch.setattr(generation_tasks, "ResumeGenerationService", LeakyResumeGenerationService)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=True,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-redact")

    state_service = KeyedStateService.instances[-1]
    assert state_service.error == "Generation failed during resume generation."
    assert state_service.events[-1]["message"] == "Generation failed during resume generation."
    assert "secret-token" not in str(state_service.events)
    assert "sk-sensitive" not in str(state_service.events)


@pytest.mark.asyncio
async def test_run_generation_validation_failure_uses_safe_public_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeRepositoryService.fail_with_message = "validation failed with token secret-token"

    await generation_tasks.run_generation.original_func("gen-validation")

    state_service = FakeStateService.instances[-1]
    assert state_service.error == "Generation failed during repository validation."
    assert state_service.events[-1]["message"] == "Generation failed during repository validation."
    assert "secret-token" not in str(state_service.events)


@pytest.mark.asyncio
async def test_run_generation_failure_logs_safe_exception_type_without_secret_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeRepositoryService.fail_with_message = "validation failed with token secret-token"

    await generation_tasks.run_generation.original_func("gen-validation")

    assert "Generation job failed" in caplog.text
    assert "gen-validation" in caplog.text
    assert "repository validation" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "validation failed with token secret-token" not in caplog.text
    assert "secret-token" not in caplog.text


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
    assert state_service.error == "Generation failed during repository analysis."
    assert state_service.events[-1]["event_type"] == "failed"
    assert state_service.events[-1]["status"] is GenerationStatus.FAILED
    assert checkout_service.cleaned == [checkout_service.checkout_result]
    assert state_service.redis.closed is True
