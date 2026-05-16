from fastapi import APIRouter

from gitresume.api.routes import (
    generations,
    health,
    models,
    oauth_providers,
    repositories,
    session,
    settings,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(session.router, tags=["session"])
api_router.include_router(repositories.router, tags=["repositories"])
api_router.include_router(models.router, tags=["models"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(oauth_providers.router, tags=["oauth-providers"])
api_router.include_router(generations.router, tags=["generations"])
