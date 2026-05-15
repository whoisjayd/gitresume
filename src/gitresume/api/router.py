from fastapi import APIRouter

from gitresume.api.routes import generations, health, repositories, session

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(session.router, tags=["session"])
api_router.include_router(repositories.router, tags=["repositories"])
api_router.include_router(generations.router, tags=["generations"])
