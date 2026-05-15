from secrets import token_urlsafe
from typing import Any, NoReturn
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from gitresume.core.config import Settings
from gitresume.schemas.session import SessionResponse

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def get_request_settings(request: Request) -> Settings:
    return request.app.state.settings


def ensure_oauth_configured(settings: Settings) -> None:
    if (
        not settings.github_client_id
        or not settings.github_client_secret
        or not settings.callback_url
    ):
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured. Set GITHUB_CLIENT_ID, "
            "GITHUB_CLIENT_SECRET, and CALLBACK_URL.",
        )


def build_session_response(session: dict[str, Any], settings: Settings) -> SessionResponse:
    is_authenticated = bool(session.get("is_authenticated"))
    return SessionResponse(
        is_authenticated=is_authenticated,
        github_user=session.get("github_user"),
        github_user_id=session.get("github_user_id"),
        app_mode=settings.app_mode,
        login_required=settings.app_mode == "hosted" and not is_authenticated,
    )


def safe_post_login_redirect(session: dict[str, Any]) -> str:
    redirect_path = session.pop("post_login_redirect", None)
    if (
        isinstance(redirect_path, str)
        and redirect_path.startswith("/")
        and not redirect_path.startswith("//")
    ):
        return redirect_path
    return "/"


def is_safe_redirect_path(redirect_path: str) -> bool:
    return redirect_path.startswith("/") and not redirect_path.startswith("//")


def fail_oauth(session: dict[str, Any], status_code: int, detail: str) -> NoReturn:
    session.pop("post_login_redirect", None)
    raise HTTPException(status_code=status_code, detail=detail)


@router.get("/session", response_model=SessionResponse)
async def read_session(request: Request) -> SessionResponse:
    session = getattr(request, "session", {})
    return build_session_response(session, get_request_settings(request))


@router.get("/session/login")
async def login(request: Request, next: str | None = None) -> RedirectResponse:  # noqa: A002
    settings = get_request_settings(request)
    ensure_oauth_configured(settings)

    state = token_urlsafe(32)
    request.session["github_oauth_state"] = state
    request.session.pop("post_login_redirect", None)
    if next and is_safe_redirect_path(next):
        request.session["post_login_redirect"] = next
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": str(settings.callback_url),
            "scope": "read:user",
            "state": state,
        }
    )
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{query}")


@router.get("/session/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None
) -> RedirectResponse:
    settings = get_request_settings(request)
    ensure_oauth_configured(settings)

    expected_state = request.session.get("github_oauth_state")
    if not state or not expected_state or state != expected_state:
        request.session.clear()
        raise HTTPException(status_code=400, detail="Invalid GitHub OAuth state.")
    request.session.pop("github_oauth_state", None)
    if not code:
        fail_oauth(request.session, 400, "Missing GitHub OAuth code.")

    async with httpx.AsyncClient() as client:
        try:
            token_response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": str(settings.callback_url),
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            if not isinstance(token_payload, dict):
                fail_oauth(request.session, 502, "GitHub OAuth token exchange failed.")
            access_token = token_payload.get("access_token")
        except (httpx.HTTPError, ValueError):
            fail_oauth(request.session, 502, "GitHub OAuth token exchange failed.")
        if not access_token:
            fail_oauth(request.session, 502, "GitHub OAuth token exchange failed.")

        try:
            user_response = await client.get(
                GITHUB_USER_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            user = user_response.json()
            if not isinstance(user, dict):
                fail_oauth(request.session, 502, "GitHub user lookup failed.")
        except (httpx.HTTPError, ValueError):
            fail_oauth(request.session, 502, "GitHub user lookup failed.")

    redirect_path = safe_post_login_redirect(request.session)
    request.session.clear()
    request.session["is_authenticated"] = True
    request.session["github_user"] = user.get("login")
    request.session["github_user_id"] = str(user.get("id")) if user.get("id") is not None else None
    return RedirectResponse(redirect_path)


@router.post("/session/logout", response_model=SessionResponse)
async def logout(request: Request) -> SessionResponse:
    request.session.clear()
    return build_session_response(request.session, get_request_settings(request))
