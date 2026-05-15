from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from gitresume.api.router import api_router
from gitresume.core.config import Settings, get_settings
from gitresume.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    # Starlette sessions are signed cookies, not encrypted storage. Values are
    # readable by the browser, so never store OAuth tokens or provider secrets.
    session_https_only = (
        settings.environment == "production"
        if settings.session_cookie_https_only is None
        else settings.session_cookie_https_only
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        https_only=session_https_only,
        same_site=settings.session_cookie_same_site,
        max_age=settings.session_cookie_max_age_seconds,
    )
    app.include_router(api_router)
    return app


app = create_app()
