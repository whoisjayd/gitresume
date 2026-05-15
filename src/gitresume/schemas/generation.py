from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
)

from gitresume.services.repository_service import parse_github_repository_url


def utc_now() -> datetime:
    return datetime.now(UTC)


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    repo_url: str = Field(validation_alias="repoUrl", serialization_alias="repoUrl")
    job_description: str | None = Field(
        default=None,
        validation_alias="jobDescription",
        serialization_alias="jobDescription",
    )
    github_token: SecretStr | None = Field(
        default=None,
        validation_alias="githubToken",
        serialization_alias="githubToken",
        exclude=True,
        repr=False,
    )
    model: str | None = Field(default=None, validation_alias="model", serialization_alias="model")
    provider_key_id: str | None = Field(
        default=None,
        validation_alias="providerKeyId",
        serialization_alias="providerKeyId",
    )

    @field_validator("repo_url")
    @classmethod
    def normalize_repo_url(cls, value: str) -> str:
        normalized = str(TypeAdapter(AnyHttpUrl).validate_python(value)).rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized.removesuffix(".git")
        reference = parse_github_repository_url(normalized)
        return f"{reference.canonical_url}/"


class GenerationCreateResponse(BaseModel):
    generation_id: str = Field(serialization_alias="generationId")
    status_url: str = Field(serialization_alias="statusUrl")
    events_url: str = Field(serialization_alias="eventsUrl")
    redirect_path: str = Field(serialization_alias="redirectPath")


class GenerationEvent(BaseModel):
    generation_id: str = Field(serialization_alias="generationId")
    event_type: str = Field(serialization_alias="eventType")
    status: GenerationStatus | None = None
    message: str
    sequence: int
    data: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now, serialization_alias="createdAt")


class GenerationState(BaseModel):
    generation_id: str = Field(serialization_alias="generationId")
    status: GenerationStatus
    repository_url: str = Field(serialization_alias="repositoryUrl")
    job_description: str | None = Field(default=None, serialization_alias="jobDescription")
    result: dict[str, Any] | None = None
    error: str | None = None
    task_id: str | None = Field(default=None, serialization_alias="taskId")
    model: str | None = Field(default=None, serialization_alias="model")
    provider_key_id: str | None = Field(
        default=None,
        serialization_alias="providerKeyId",
        exclude=True,
    )
    created_at: datetime = Field(default_factory=utc_now, serialization_alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, serialization_alias="updatedAt")
