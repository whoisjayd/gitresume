from fastapi import APIRouter, Request

from gitresume.schemas.session import SessionResponse

router = APIRouter()


@router.get("/session", response_model=SessionResponse)
async def read_session(request: Request) -> SessionResponse:
    session = getattr(request, "session", {})
    github_user = session.get("github_user")
    return SessionResponse(
        is_authenticated=bool(session.get("is_authenticated")),
        github_user=github_user,
    )
