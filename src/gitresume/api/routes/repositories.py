from fastapi import APIRouter, HTTPException, Query, Request, status

from gitresume.schemas.repository import RepositoryValidationResponse
from gitresume.services.repository_service import RepositoryValidationError, repository_service

router = APIRouter(prefix="/repositories")


@router.get("/validate", response_model=RepositoryValidationResponse, response_model_by_alias=True)
async def validate_repository(
    request: Request,
    repo_url: str = Query(..., min_length=1),
    github_token: str | None = Query(default=None, min_length=1),
) -> RepositoryValidationResponse:
    settings = request.app.state.settings
    token = github_token or settings.github_token
    try:
        result = await repository_service.validate_access(repo_url, token)
    except RepositoryValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": error.code, "message": str(error)},
        ) from error

    return RepositoryValidationResponse(**result)
