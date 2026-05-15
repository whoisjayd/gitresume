from datetime import UTC, datetime

import pytest

from gitresume.schemas.generation import (
    GenerationCreateRequest,
    GenerationCreateResponse,
    GenerationEvent,
    GenerationState,
    GenerationStatus,
)


def test_generation_payloads_serialize_with_camel_case_aliases() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    response = GenerationCreateResponse(
        generation_id="gen-123",
        status_url="/api/generations/gen-123",
        events_url="/api/generations/gen-123/events",
        redirect_path="/generations/gen-123",
    )
    event = GenerationEvent(
        generation_id="gen-123",
        event_type="status",
        status=GenerationStatus.GENERATING,
        message="Generating resume bullets",
        sequence=2,
        data={"stage": "resume"},
        created_at=created_at,
    )
    state = GenerationState(
        generation_id="gen-123",
        status=GenerationStatus.GENERATING,
        repository_url="https://github.com/example/project",
        job_description="Python backend role",
        created_at=created_at,
        updated_at=created_at,
    )

    assert response.model_dump(by_alias=True) == {
        "generationId": "gen-123",
        "statusUrl": "/api/generations/gen-123",
        "eventsUrl": "/api/generations/gen-123/events",
        "redirectPath": "/generations/gen-123",
    }
    assert event.model_dump(by_alias=True, mode="json") == {
        "generationId": "gen-123",
        "eventType": "status",
        "status": "generating",
        "message": "Generating resume bullets",
        "sequence": 2,
        "data": {"stage": "resume"},
        "createdAt": "2026-01-02T03:04:05Z",
    }
    assert state.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "generationId": "gen-123",
        "status": "generating",
        "repositoryUrl": "https://github.com/example/project",
        "jobDescription": "Python backend role",
        "createdAt": "2026-01-02T03:04:05Z",
        "updatedAt": "2026-01-02T03:04:05Z",
    }


@pytest.mark.parametrize("token_field", ["githubToken", "github_token"])
def test_generation_create_request_accepts_github_token_alias(token_field: str) -> None:
    request = GenerationCreateRequest.model_validate(
        {
            "repoUrl": "https://github.com/example/project",
            token_field: "secret-token",
        }
    )

    assert request.github_token == "secret-token"
    assert request.model_dump(by_alias=True)["githubToken"] == "secret-token"


def test_generation_create_request_normalizes_github_git_suffix() -> None:
    request = GenerationCreateRequest.model_validate(
        {"repoUrl": "https://github.com/example/project.git"}
    )

    assert request.repo_url == "https://github.com/example/project/"


@pytest.mark.parametrize(
    "repo_url",
    [
        "https://token@github.com/example/project",
        "https://gitlab.com/example/project",
        "https://github.com/example/project/issues",
    ],
)
def test_generation_create_request_rejects_unsupported_or_sensitive_repo_urls(
    repo_url: str,
) -> None:
    with pytest.raises(ValueError):
        GenerationCreateRequest.model_validate({"repoUrl": repo_url})
