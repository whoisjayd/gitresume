from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, SecretStr

from gitresume.schemas.repository import RepositoryValidationResponse
from gitresume.services.repository_service import RepositoryValidationError, repository_service

router = APIRouter(prefix="/repositories")


class RepositoryValidationRequest(BaseModel):
    repo_url: str = Field(validation_alias="repoUrl", serialization_alias="repoUrl")
    github_token: SecretStr | None = Field(
        default=None,
        validation_alias="githubToken",
        serialization_alias="githubToken",
        exclude=True,
        repr=False,
    )


@router.get("/validate", response_model=RepositoryValidationResponse, response_model_by_alias=True)
async def validate_repository(
    request: Request,
    repo_url: str = Query(..., min_length=1),
) -> RepositoryValidationResponse:
    if "github_token" in request.query_params or "githubToken" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub tokens must be sent in the POST body, not query parameters.",
        )
    settings = request.app.state.settings
    token = settings.github_token
    return await _validate_repository(repo_url, token)


@router.post("/validate", response_model=RepositoryValidationResponse, response_model_by_alias=True)
async def validate_repository_with_body(
    body: RepositoryValidationRequest,
    request: Request,
) -> RepositoryValidationResponse:
    settings = request.app.state.settings
    token = (
        body.github_token.get_secret_value()
        if body.github_token is not None
        else settings.github_token
    )
    return await _validate_repository(body.repo_url, token)


async def _validate_repository(
    repo_url: str, github_token: str | None
) -> RepositoryValidationResponse:
    try:
        result = await repository_service.validate_access(repo_url, github_token)
    except RepositoryValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": error.code, "message": str(error)},
        ) from error

    return RepositoryValidationResponse(**result)
