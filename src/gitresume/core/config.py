from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from gitresume.core.crypto import StringEncryptor


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "GitResume"
    environment: Literal["development", "test", "production"] = "development"
    app_mode: Literal["self_hosted", "hosted"] = "self_hosted"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:5173"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])

    session_secret_key: str = "change-me-in-production"
    session_cookie_https_only: bool | None = None
    session_cookie_same_site: Literal["lax", "strict", "none"] = "lax"
    session_cookie_max_age_seconds: int = 1_209_600
    redis_url: str | None = None

    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_token: str | None = None
    callback_url: AnyHttpUrl | None = None

    allow_saved_byok: bool = False
    settings_encryption_key: SecretStr | None = None

    ai_model: str = "gemini/gemini-1.5-flash"
    ai_temperature: float = 0.2
    ai_timeout_seconds: int = 90

    max_repo_size_mb: int = 100
    max_repo_files: int = 200
    ranked_context_file_limit: int = 20
    ranked_context_chars_per_file: int = 8_000
    generation_ttl_seconds: int = 86_400
    generation_event_max_len: int = 200

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_saved_byok_encryption(self) -> "Settings":
        placeholder_session_secrets = {"change-me", "change-me-in-production"}
        session_secret = self.session_secret_key.strip()
        if self.environment == "production" and (
            session_secret in placeholder_session_secrets or len(session_secret) < 32
        ):
            raise ValueError(
                "session_secret_key must be at least 32 characters and changed in production"
            )
        if self.settings_encryption_key:
            encryptor = StringEncryptor(self.settings_encryption_key.get_secret_value())
            encrypted = encryptor.encrypt("settings-check")
            if encryptor.decrypt(encrypted) != "settings-check":
                raise ValueError("settings_encryption_key is not usable for encryption")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
