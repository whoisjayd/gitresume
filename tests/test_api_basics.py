import pytest
from fastapi.testclient import TestClient

from gitresume.core.config import Settings
from gitresume.main import create_app
from gitresume.services.repository_service import parse_github_repository_url


def make_client() -> TestClient:
    settings = Settings(
        environment="test",
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
    )
    return TestClient(create_app(settings))


def test_health_endpoint_reports_service_ready_without_redis() -> None:
    client = make_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "gitresume-api",
        "environment": "test",
        "redis_configured": False,
    }


def test_session_endpoint_defaults_to_logged_out() -> None:
    client = make_client()

    response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json() == {
        "isAuthenticated": False,
        "githubUser": None,
        "githubUserId": None,
        "appMode": "self_hosted",
        "loginRequired": False,
    }


@pytest.mark.parametrize(
    ("repo_url", "owner", "name"),
    [
        ("https://github.com/owner/repo", "owner", "repo"),
        ("https://github.com/owner/repo.git", "owner", "repo"),
    ],
)
def test_parse_github_repository_url_accepts_github_owner_repo_urls(
    repo_url: str, owner: str, name: str
) -> None:
    reference = parse_github_repository_url(repo_url)

    assert reference.owner == owner
    assert reference.name == name
    assert reference.full_name == f"{owner}/{name}"


@pytest.mark.parametrize(
    "repo_url",
    [
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/issues",
    ],
)
def test_repository_validate_endpoint_rejects_invalid_urls(repo_url: str) -> None:
    client = make_client()

    response = client.get("/api/repositories/validate", params={"repo_url": repo_url})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_repository_url"
