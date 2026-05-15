from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.generation_task_dispatcher import TaskiqGenerationTaskDispatcher


async def get_generation_state_service(
    request: Request,
) -> AsyncIterator[RedisGenerationStateService]:
    redis_url = request.app.state.settings.redis_url
    if not redis_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is required for generation jobs.",
        )

    app_redis = getattr(request.app.state, "redis", None)
    settings = request.app.state.settings
    if app_redis is not None:
        yield RedisGenerationStateService(
            app_redis,
            generation_ttl_seconds=settings.generation_ttl_seconds,
            generation_event_max_len=settings.generation_event_max_len,
        )
        return

    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        yield RedisGenerationStateService(
            redis,
            generation_ttl_seconds=settings.generation_ttl_seconds,
            generation_event_max_len=settings.generation_event_max_len,
        )
    finally:
        await redis.aclose()


def get_generation_task_dispatcher() -> TaskiqGenerationTaskDispatcher:
    return TaskiqGenerationTaskDispatcher()
