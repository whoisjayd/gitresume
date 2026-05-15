from typing import Literal

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    is_authenticated: bool = Field(serialization_alias="isAuthenticated")
    github_user: str | None = Field(default=None, serialization_alias="githubUser")
    github_user_id: str | None = Field(default=None, serialization_alias="githubUserId")
    app_mode: Literal["self_hosted", "hosted"] = Field(serialization_alias="appMode")
    login_required: bool = Field(serialization_alias="loginRequired")
