from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    redis_configured: bool
