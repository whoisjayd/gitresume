from pydantic import BaseModel


class SessionResponse(BaseModel):
    is_authenticated: bool
    github_user: str | None = None
