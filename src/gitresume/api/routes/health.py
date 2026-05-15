from fastapi import APIRouter, Request

from gitresume.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service="gitresume-api",
        environment=settings.environment,
        redis_configured=settings.redis_url is not None,
    )
