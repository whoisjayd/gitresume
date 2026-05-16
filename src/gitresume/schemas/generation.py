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
    provider_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="providerApiKey",
        serialization_alias="providerApiKey",
        exclude=True,
        repr=False,
    )
    model: str | None = Field(default=None, validation_alias="model", serialization_alias="model")
    analysis_author: str | None = Field(
        default=None,
        validation_alias="analysisAuthor",
        serialization_alias="analysisAuthor",
        max_length=200,
        exclude=True,
        repr=False,
    )
    analysis_days: int | None = Field(
        default=None,
        validation_alias="analysisDays",
        serialization_alias="analysisDays",
        ge=1,
        le=3650,
        exclude=True,
    )
    provider_key_id: str | None = Field(
        default=None,
        validation_alias="providerKeyId",
        serialization_alias="providerKeyId",
    )
    provider_key_scope: str | None = Field(default=None, exclude=True, repr=False)
    oauth_provider_scope: str | None = Field(default=None, exclude=True, repr=False)
    owner_scope: str | None = Field(default=None, exclude=True, repr=False)

    @field_validator("repo_url")
    @classmethod
    def normalize_repo_url(cls, value: str) -> str:
        normalized = str(TypeAdapter(AnyHttpUrl).validate_python(value)).rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized.removesuffix(".git")
        reference = parse_github_repository_url(normalized)
        return f"{reference.canonical_url}/"

    @field_validator("analysis_author")
    @classmethod
    def normalize_analysis_author(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lstrip("@")
        if not normalized or "\x00" in normalized:
            raise ValueError("analysis author must be non-empty and must not contain NUL bytes")
        return normalized


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
    analysis_author: str | None = Field(default=None, exclude=True)
    analysis_days: int | None = Field(default=None, exclude=True)
    provider_key_id: str | None = Field(
        default=None,
        serialization_alias="providerKeyId",
        exclude=True,
    )
    provider_key_scope: str | None = Field(default=None, exclude=True)
    oauth_provider_scope: str | None = Field(default=None, exclude=True)
    owner_scope: str | None = Field(default=None, exclude=True)
    created_at: datetime = Field(default_factory=utc_now, serialization_alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, serialization_alias="updatedAt")
