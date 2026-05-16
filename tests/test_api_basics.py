import pytest
from fastapi.testclient import TestClient

from gitresume.api.routes import repositories
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


def test_settings_parses_comma_separated_allowed_hosts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1,api")
    monkeypatch.setenv(
        "SESSION_SECRET_KEY", "release-smoke-secret-with-more-than-thirty-two-characters"
    )
    monkeypatch.setenv("ENVIRONMENT", "production")

    settings = Settings()

    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "api"]


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


@pytest.mark.parametrize("token_query_name", ["github_token", "githubToken"])
def test_repository_validate_get_rejects_github_token_query(token_query_name: str) -> None:
    client = make_client()

    response = client.get(
        "/api/repositories/validate",
        params={
            "repo_url": "https://github.com/example/project",
            token_query_name: "secret-token",
        },
    )

    assert response.status_code == 400
    assert "secret-token" not in response.text


def test_repository_validate_post_accepts_github_token_body_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str | None] = {}

    class FakeRepositoryService:
        async def validate_access(
            self, repo_url: str, github_token: str | None = None
        ) -> dict[str, object]:
            observed["repo_url"] = repo_url
            observed["github_token"] = github_token
            return {
                "success": True,
                "owner": "example",
                "repo_name": "project",
                "full_name": "example/project",
                "canonical_url": "https://github.com/example/project",
                "is_public": False,
                "error_code": None,
                "error_message": None,
            }

    monkeypatch.setattr(repositories, "repository_service", FakeRepositoryService())
    client = make_client()

    response = client.post(
        "/api/repositories/validate",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "secret-token"},
    )

    assert response.status_code == 200
    assert observed == {
        "repo_url": "https://github.com/example/project",
        "github_token": "secret-token",
    }
    assert response.json()["canonicalUrl"] == "https://github.com/example/project"
    assert "secret-token" not in response.text
