from taskiq_redis import RedisStreamBroker

from gitresume.core.config import get_settings


def create_broker() -> RedisStreamBroker:
    redis_url = get_settings().redis_url or "redis://localhost:6379/0"
    return RedisStreamBroker(redis_url)


broker = create_broker()
