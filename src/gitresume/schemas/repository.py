from pydantic import BaseModel, Field


class RepositoryValidationResponse(BaseModel):
    success: bool
    owner: str
    repo_name: str = Field(serialization_alias="repoName")
    full_name: str = Field(serialization_alias="fullName")
    canonical_url: str = Field(serialization_alias="canonicalUrl")
    is_public: bool = Field(serialization_alias="isPublic")
    error_code: str | None = Field(default=None, serialization_alias="errorCode")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")
