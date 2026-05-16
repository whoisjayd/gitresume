from fastapi.testclient import TestClient

from gitresume.api.routes import repositories
from gitresume.core.config import Settings
from gitresume.main import create_app


def make_client(*, app_mode: str, github_token: str | None = "server-token") -> TestClient:
    settings = Settings(
        environment="test",
        app_mode=app_mode,
        github_token=github_token,
        session_secret_key="test-secret",
        allowed_hosts=["testserver"],
        frontend_origin="http://testserver",
    )
    return TestClient(create_app(settings))


def test_repository_validate_get_uses_server_token_only_in_self_hosted_mode(monkeypatch) -> None:
    observed_tokens: list[str | None] = []

    class FakeRepositoryService:
        async def validate_access(
            self, repo_url: str, github_token: str | None = None
        ) -> dict[str, object]:
            observed_tokens.append(github_token)
            return {
                "success": True,
                "owner": "example",
                "repo_name": "project",
                "full_name": "example/project",
                "canonical_url": repo_url,
                "is_public": True,
                "error_code": None,
                "error_message": None,
            }

    monkeypatch.setattr(repositories, "repository_service", FakeRepositoryService())
    client = make_client(app_mode="self_hosted", github_token="server-token")

    response = client.get(
        "/api/repositories/validate",
        params={"repo_url": "https://github.com/example/project"},
    )

    assert response.status_code == 200
    assert observed_tokens == ["server-token"]


def test_repository_validate_get_hosted_mode_validates_anonymously(monkeypatch) -> None:
    observed_tokens: list[str | None] = []

    class FakeRepositoryService:
        async def validate_access(
            self, repo_url: str, github_token: str | None = None
        ) -> dict[str, object]:
            observed_tokens.append(github_token)
            return {
                "success": True,
                "owner": "example",
                "repo_name": "project",
                "full_name": "example/project",
                "canonical_url": repo_url,
                "is_public": True,
                "error_code": None,
                "error_message": None,
            }

    monkeypatch.setattr(repositories, "repository_service", FakeRepositoryService())
    client = make_client(app_mode="hosted", github_token="server-token")

    response = client.get(
        "/api/repositories/validate",
        params={"repo_url": "https://github.com/example/project"},
    )

    assert response.status_code == 200
    assert observed_tokens == [None]


def test_repository_validate_post_hosted_mode_without_token_validates_anonymously(
    monkeypatch,
) -> None:
    observed_tokens: list[str | None] = []

    class FakeRepositoryService:
        async def validate_access(
            self, repo_url: str, github_token: str | None = None
        ) -> dict[str, object]:
            observed_tokens.append(github_token)
            return {
                "success": True,
                "owner": "example",
                "repo_name": "project",
                "full_name": "example/project",
                "canonical_url": repo_url,
                "is_public": True,
                "error_code": None,
                "error_message": None,
            }

    monkeypatch.setattr(repositories, "repository_service", FakeRepositoryService())
    client = make_client(app_mode="hosted", github_token="server-token")

    response = client.post(
        "/api/repositories/validate",
        json={"repoUrl": "https://github.com/example/project"},
    )

    assert response.status_code == 200
    assert observed_tokens == [None]


def test_repository_validate_post_hosted_mode_uses_explicit_body_token(monkeypatch) -> None:
    observed_tokens: list[str | None] = []

    class FakeRepositoryService:
        async def validate_access(
            self, repo_url: str, github_token: str | None = None
        ) -> dict[str, object]:
            observed_tokens.append(github_token)
            return {
                "success": True,
                "owner": "example",
                "repo_name": "project",
                "full_name": "example/project",
                "canonical_url": repo_url,
                "is_public": False,
                "error_code": None,
                "error_message": None,
            }

    monkeypatch.setattr(repositories, "repository_service", FakeRepositoryService())
    client = make_client(app_mode="hosted", github_token="server-token")

    response = client.post(
        "/api/repositories/validate",
        json={"repoUrl": "https://github.com/example/project", "githubToken": "body-token"},
    )

    assert response.status_code == 200
    assert observed_tokens == ["body-token"]
    assert "body-token" not in response.text
