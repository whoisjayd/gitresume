from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gitresume.core.config import Settings
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
    default_token: str | None = "secret-token"

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
        self.token: str | None = self.__class__.default_token
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
    validated_tokens: list[str | None] = []

    async def validate_access(
        self, repo_url: str, github_token: str | None = None
    ) -> dict[str, Any]:
        assert repo_url == "https://github.com/example/project/"
        assert github_token in {"secret-token", "server-token", None}
        self.__class__.validated_tokens.append(github_token)
        if self.fail_with_message is not None:
            raise RuntimeError(self.fail_with_message)
        return {"success": True}


class FakeCheckoutService:
    instances: list["FakeCheckoutService"] = []
    checkout_tokens: list[str | None] = []
    fail_cleanup = False

    def __init__(self) -> None:
        self.checkout_result = FakeCheckout(local_path=Path("D:/tmp/fake-checkout"))
        self.cleaned: list[FakeCheckout] = []
        self.__class__.instances.append(self)

    async def checkout(self, repo_url: str, github_token: str | None = None) -> FakeCheckout:
        assert repo_url == "https://github.com/example/project/"
        assert github_token in {"secret-token", "server-token", None}
        self.__class__.checkout_tokens.append(github_token)
        return self.checkout_result

    def cleanup_checkout(self, checkout: FakeCheckout) -> None:
        if self.__class__.fail_cleanup:
            raise RuntimeError("cleanup failed with secret-token")
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
        assert (
            '"strategy": "unit-test"' in repo_context
            or "Evidence brief: FastAPI in src/app.py:1-2" in repo_context
            or '"contribution_scope"' in repo_context
        )
        assert job_description == "Backend role"
        self.calls.append(
            {
                "repo_context": repo_context,
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


class FakeRepositoryInvestigationService:
    calls: list[dict[str, Any]] = []
    fail = False

    async def investigate(self, **kwargs: Any) -> object:
        self.__class__.calls.append(kwargs)
        if self.__class__.fail:
            raise RuntimeError("investigation failed with sensitive repository content")
        return SimpleNamespace(
            to_prompt_context=lambda: "Evidence brief: FastAPI in src/app.py:1-2"
        )


class FakeContributionAnalysis:
    touched_files = ["src/app.py"]

    def to_prompt_context(self) -> str:
        return "git standup Jaydeep Solanki -d 300\n- src/app.py"


class FakeEmptyContributionAnalysis:
    touched_files: list[str] = []

    def to_prompt_context(self) -> str:
        return "git standup Jaydeep Solanki -d 300\nNo matching author-touched files were found."


class FakeContributionAnalysisService:
    calls: list[dict[str, Any]] = []

    def analyze(self, repo_root: Path, **kwargs: Any) -> FakeContributionAnalysis:
        self.__class__.calls.append({"repo_root": repo_root, **kwargs})
        return FakeContributionAnalysis()


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
    FakeStateService.default_token = "secret-token"
    FakeCheckoutService.instances.clear()
    FakeCheckoutService.checkout_tokens.clear()
    FakeCheckoutService.fail_cleanup = False
    FakeRepositoryService.fail_with_message = None
    FakeRepositoryService.validated_tokens.clear()
    FakeResumeGenerationService.calls.clear()
    FakeRepositoryInvestigationService.calls.clear()
    FakeRepositoryInvestigationService.fail = False
    FakeContributionAnalysisService.calls.clear()
    monkeypatch.setattr(generation_tasks, "Redis", FakeRedis)
    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", FakeStateService)
    monkeypatch.setattr(generation_tasks, "GitHubRepositoryService", FakeRepositoryService)
    monkeypatch.setattr(generation_tasks, "RepositoryCheckoutService", FakeCheckoutService)
    monkeypatch.setattr(generation_tasks, "RepositoryIngestionService", FakeIngestionService)
    monkeypatch.setattr(
        generation_tasks, "RepositoryInvestigationService", FakeRepositoryInvestigationService
    )
    monkeypatch.setattr(
        generation_tasks, "ContributionAnalysisService", FakeContributionAnalysisService
    )
    monkeypatch.setattr(generation_tasks, "ResumeGenerationService", FakeResumeGenerationService)
    monkeypatch.setattr(generation_tasks, "LiteLLMResumeClient", FakeLiteLLMResumeClient)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
            github_token=None,
            enable_guided_analysis=False,
            guided_analysis_max_actions=4,
            guided_analysis_max_chars_per_observation=500,
            guided_analysis_max_observations=4,
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
async def test_run_generation_with_guided_analysis_uses_evidence_brief_context_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="openai/gpt-4o-mini",
            settings_encryption_key=None,
            github_token=None,
            enable_guided_analysis=True,
            guided_analysis_max_actions=7,
            guided_analysis_max_chars_per_observation=123,
            guided_analysis_max_observations=3,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-guided")

    state_service = FakeStateService.instances[-1]
    assert [event["message"] for event in state_service.events] == [
        "Validating repository access",
        "Cloning repository",
        "Analyzing and packing repository context",
        "Investigating repository evidence",
        "Generating resume",
        "Generation complete",
    ]
    assert (
        "Evidence brief: FastAPI in src/app.py:1-2"
        in FakeResumeGenerationService.calls[-1]["repo_context"]
    )
    assert '"strategy": "unit-test"' not in FakeResumeGenerationService.calls[-1]["repo_context"]
    investigation_call = FakeRepositoryInvestigationService.calls[-1]
    assert investigation_call["repo_root"] == Path("D:/tmp/fake-checkout")
    assert investigation_call["model"] == "openai/gpt-4o-mini"
    assert investigation_call["max_actions"] == 7
    assert investigation_call["max_chars_per_observation"] == 123
    assert investigation_call["max_observations"] == 3


@pytest.mark.asyncio
async def test_run_generation_guided_analysis_failure_falls_back_to_original_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeRepositoryInvestigationService.fail = True
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
            github_token=None,
            enable_guided_analysis=True,
            guided_analysis_max_actions=4,
            guided_analysis_max_chars_per_observation=500,
            guided_analysis_max_observations=4,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-guided-fallback")

    state_service = FakeStateService.instances[-1]
    assert state_service.result is not None
    assert '"strategy": "unit-test"' in FakeResumeGenerationService.calls[-1]["repo_context"]
    assert "Guided repository investigation failed" in caplog.text
    assert "sensitive repository content" not in caplog.text


@pytest.mark.asyncio
async def test_run_generation_guided_analysis_can_scope_to_author_contributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class AuthorScopedStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={"analysis_author": "Jaydeep Solanki", "analysis_days": 300}
            )

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", AuthorScopedStateService)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="openai/gpt-4o-mini",
            settings_encryption_key=None,
            github_token=None,
            enable_guided_analysis=True,
            enable_contribution_analysis=True,
            contribution_analysis_default_days=90,
            contribution_analysis_max_commits=50,
            contribution_analysis_max_files=100,
            guided_analysis_max_actions=4,
            guided_analysis_max_chars_per_observation=500,
            guided_analysis_max_observations=4,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-author-scope")

    assert FakeContributionAnalysisService.calls == [
        {
            "repo_root": Path("D:/tmp/fake-checkout"),
            "author": "Jaydeep Solanki",
            "days": 300,
            "max_commits": 50,
            "max_files": 100,
        }
    ]
    investigation_call = FakeRepositoryInvestigationService.calls[-1]
    assert investigation_call["allowed_paths"] == {"src/app.py"}
    assert "git standup Jaydeep Solanki -d 300" in investigation_call["contribution_context"]
    assert AuthorScopedStateService.instances[-1].events[3]["data"] == {
        "stage": "guided-evidence-investigation",
        "analysisAuthor": "Jaydeep Solanki",
        "contributedFileCount": 1,
    }


@pytest.mark.asyncio
async def test_run_generation_author_scope_empty_contributions_never_falls_back_to_full_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeRepositoryInvestigationService.fail = True

    class EmptyContributionAnalysisService(FakeContributionAnalysisService):
        def analyze(self, repo_root: Path, **kwargs: Any) -> FakeEmptyContributionAnalysis:
            self.__class__.calls.append({"repo_root": repo_root, **kwargs})
            return FakeEmptyContributionAnalysis()

    class AuthorScopedStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={"analysis_author": "Jaydeep Solanki", "analysis_days": 300}
            )

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", AuthorScopedStateService)
    monkeypatch.setattr(
        generation_tasks, "ContributionAnalysisService", EmptyContributionAnalysisService
    )
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="openai/gpt-4o-mini",
            settings_encryption_key=None,
            github_token=None,
            enable_guided_analysis=True,
            enable_contribution_analysis=True,
            contribution_analysis_default_days=90,
            contribution_analysis_max_commits=50,
            contribution_analysis_max_files=100,
            guided_analysis_max_actions=4,
            guided_analysis_max_chars_per_observation=500,
            guided_analysis_max_observations=4,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-author-empty-fallback")

    repo_context = FakeResumeGenerationService.calls[-1]["repo_context"]
    assert '"strategy": "unit-test"' not in repo_context
    assert "git standup Jaydeep Solanki -d 300" in repo_context
    assert "No matching author-touched files were found." in repo_context
    investigation_call = FakeRepositoryInvestigationService.calls[-1]
    assert investigation_call["allowed_paths"] == set()
    assert '"strategy": "unit-test"' not in str(investigation_call["initial_context"])
    assert "Guided repository investigation failed" in caplog.text


@pytest.mark.asyncio
async def test_run_generation_uses_server_github_token_when_generation_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeStateService.default_token = None
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            app_mode="self_hosted",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
            github_token=FakeSecret("server-token"),
            enable_guided_analysis=False,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-server-token")

    assert FakeRepositoryService.validated_tokens == ["server-token"]
    assert FakeCheckoutService.checkout_tokens == ["server-token"]
    assert FakeStateService.instances[-1].token is None


@pytest.mark.asyncio
async def test_run_generation_hosted_mode_does_not_use_server_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeStateService.default_token = None
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            app_mode="hosted",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
            github_token=FakeSecret("server-token"),
            enable_guided_analysis=False,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-hosted-no-server-token")

    assert FakeRepositoryService.validated_tokens == [None]
    assert FakeCheckoutService.checkout_tokens == [None]
    assert FakeStateService.instances[-1].token is None


@pytest.mark.asyncio
async def test_run_generation_accepts_plain_string_github_token_from_real_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeStateService.default_token = None
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: Settings(
            environment="test",
            session_secret_key="test-secret",
            redis_url="redis://unit-test",
            github_token="server-token",
        ),
    )

    await generation_tasks.run_generation.original_func("gen-real-settings-token")

    assert FakeRepositoryService.validated_tokens == ["server-token"]
    assert FakeCheckoutService.checkout_tokens == ["server-token"]


@pytest.mark.asyncio
async def test_run_generation_prefers_generation_token_over_server_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=None,
            github_token=FakeSecret("server-token"),
        ),
    )

    await generation_tasks.run_generation.original_func("gen-request-token")

    assert FakeRepositoryService.validated_tokens == ["secret-token"]
    assert FakeCheckoutService.checkout_tokens == ["secret-token"]
    assert FakeStateService.instances[-1].token is None


@pytest.mark.asyncio
async def test_run_generation_closes_redis_when_checkout_cleanup_fails_and_redacts_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)
    FakeCheckoutService.fail_cleanup = True

    await generation_tasks.run_generation.original_func("gen-cleanup-fails")

    state_service = FakeStateService.instances[-1]
    assert state_service.redis.closed is True
    assert "Checkout cleanup failed" in caplog.text
    assert "secret-token" not in caplog.text


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
async def test_run_generation_uses_oauth_account_selector_for_oauth_model_without_token_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class OAuthStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={
                    "model": "github_copilot/gpt-4.1",
                    "oauth_provider_scope": "global",
                }
            )

    class FakeOAuthProviderStore:
        calls: list[dict[str, str]] = []

        def __init__(self, redis: object, encryptor: object) -> None:
            self.redis = redis
            self.encryptor = encryptor

        async def select_access_token(self, scope: str, provider: str) -> str | None:
            self.calls.append({"scope": scope, "provider": provider})
            return "ghu-selected-account-token"

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", OAuthStateService)
    monkeypatch.setattr(generation_tasks, "RedisOAuthProviderStore", FakeOAuthProviderStore)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "provider_for_model", lambda model: "github_copilot")
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=False,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-oauth-selector")

    assert FakeOAuthProviderStore.calls == [{"scope": "global", "provider": "github_copilot"}]
    assert FakeResumeGenerationService.calls[-1]["provider_api_key"] == "ghu-selected-account-token"
    assert "ghu-selected-account-token" not in str(OAuthStateService.instances[-1].events)


@pytest.mark.asyncio
async def test_run_generation_uses_connected_oauth_provider_token_for_oauth_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class OAuthStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={
                    "model": "github_copilot/gpt-4.1",
                    "oauth_provider_scope": "global",
                }
            )

    class FakeOAuthProviderStore:
        calls: list[dict[str, str]] = []

        def __init__(self, redis: object, encryptor: object) -> None:
            self.redis = redis
            self.encryptor = encryptor

        async def select_access_token(self, scope: str, provider: str) -> str | None:
            self.calls.append({"scope": scope, "provider": provider})
            return "ghu-oauth-token"

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", OAuthStateService)
    monkeypatch.setattr(generation_tasks, "RedisOAuthProviderStore", FakeOAuthProviderStore)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "provider_for_model", lambda model: "github_copilot")
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=False,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-oauth")

    assert FakeOAuthProviderStore.calls == [{"scope": "global", "provider": "github_copilot"}]
    assert FakeResumeGenerationService.calls[-1]["model"] == "github_copilot/gpt-4.1"
    assert FakeResumeGenerationService.calls[-1]["provider_api_key"] == "ghu-oauth-token"
    assert FakeResumeGenerationService.calls[-1]["model_mode"] == "chat"
    assert "ghu-oauth-token" not in str(OAuthStateService.instances[-1].events)


@pytest.mark.asyncio
async def test_run_generation_oauth_litellm_failure_keeps_token_out_of_state_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class OAuthStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={
                    "model": "github_copilot/gpt-4.1",
                    "oauth_provider_scope": "global",
                }
            )

    class FakeOAuthProviderStore:
        def __init__(self, redis: object, encryptor: object) -> None:
            del redis, encryptor

        async def select_access_token(self, scope: str, provider: str) -> str | None:
            assert scope == "global"
            assert provider == "github_copilot"
            return "ghu-oauth-sensitive-token"

    class LeakyOAuthResumeGenerationService(FakeResumeGenerationService):
        async def generate(self, **kwargs: object) -> ResumeDraft:
            assert kwargs["provider_api_key"] == "ghu-oauth-sensitive-token"
            raise RuntimeError("LiteLLM failed with token ghu-oauth-sensitive-token")

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", OAuthStateService)
    monkeypatch.setattr(generation_tasks, "RedisOAuthProviderStore", FakeOAuthProviderStore)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "provider_for_model", lambda model: "github_copilot")
    monkeypatch.setattr(
        generation_tasks,
        "ResumeGenerationService",
        LeakyOAuthResumeGenerationService,
    )
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=False,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-oauth-leak")

    state_service = OAuthStateService.instances[-1]
    assert state_service.error == "Generation failed during resume generation."
    assert "ghu-oauth-sensitive-token" not in str(state_service.events)
    assert "ghu-oauth-sensitive-token" not in caplog.text
    assert "LiteLLM failed with token" not in caplog.text


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
async def test_run_generation_uses_hosted_owner_scope_for_implicit_saved_key_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_tasks = patch_worker_dependencies(monkeypatch)

    class HostedStateService(FakeStateService):
        async def get_generation(self, generation_id: str) -> GenerationState | None:
            state = await super().get_generation(generation_id)
            assert state is not None
            return state.model_copy(
                update={
                    "model": "openai/gpt-4o-mini",
                    "owner_scope": "user:12345",
                    "provider_key_scope": None,
                    "provider_key_id": None,
                }
            )

    class FakeSelectedKey:
        secret = FakeSecret("sk-hosted")

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

    monkeypatch.setattr(generation_tasks, "RedisGenerationStateService", HostedStateService)
    monkeypatch.setattr(generation_tasks, "StringEncryptor", FakeStringEncryptor)
    monkeypatch.setattr(generation_tasks, "RedisSettingsStore", FakeSettingsStore)
    monkeypatch.setattr(generation_tasks, "RedisProviderKeySelector", FakeSelector)
    monkeypatch.setattr(generation_tasks, "provider_for_model", lambda model: "openai")
    monkeypatch.setattr(
        generation_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://unit-test",
            app_mode="hosted",
            ai_model="gemini/gemini-1.5-flash",
            settings_encryption_key=FakeSecret("settings encryption passphrase"),
            allow_saved_byok=True,
            github_token=None,
        ),
    )

    await generation_tasks.run_generation.original_func("gen-hosted-model")

    assert FakeSelector.calls == [
        {
            "scope": "user:12345",
            "provider": "openai",
            "model": "openai/gpt-4o-mini",
            "provider_key_id": None,
        }
    ]
    assert FakeResumeGenerationService.calls[-1]["provider_api_key"] == "sk-hosted"


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
