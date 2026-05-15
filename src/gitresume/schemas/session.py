from typing import Literal

from pydantic import BaseModel


class SessionResponse(BaseModel):
    is_authenticated: bool
    github_user: str | None = None
    github_user_id: str | None = None
    app_mode: Literal["self_hosted", "hosted"]
    login_required: bool
