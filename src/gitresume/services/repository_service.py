import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from github import Github, GithubException


@dataclass(frozen=True)
class RepositoryReference:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.full_name}"


class RepositoryValidationError(ValueError):
    def __init__(self, message: str, code: str = "invalid_repository_url") -> None:
        super().__init__(message)
        self.code = code


def parse_github_repository_url(repo_url: str) -> RepositoryReference:
    parsed = urlparse(repo_url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RepositoryValidationError("Repository URL must start with https://github.com/.")

    path_parts = [part for part in parsed.path.removesuffix(".git").strip("/").split("/") if part]
    if len(path_parts) != 2:
        raise RepositoryValidationError("Repository URL must include an owner and repository name.")
    owner, repo_name = path_parts
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
        raise RepositoryValidationError("Repository owner is not a valid GitHub owner name.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repo_name):
        raise RepositoryValidationError("Repository name is not a valid GitHub repository name.")

    return RepositoryReference(owner=owner, name=repo_name)


class GitHubRepositoryService:
    async def validate_access(
        self, repo_url: str, github_token: str | None = None
    ) -> dict[str, object]:
        reference = parse_github_repository_url(repo_url)
        return await asyncio.to_thread(self._validate_access_sync, reference, github_token)

    def _validate_access_sync(
        self, reference: RepositoryReference, github_token: str | None
    ) -> dict[str, object]:
        try:
            github = Github(github_token) if github_token else Github()
            repo = github.get_repo(reference.full_name)
            return {
                "success": True,
                "owner": reference.owner,
                "repo_name": reference.name,
                "full_name": reference.full_name,
                "canonical_url": reference.canonical_url,
                "is_public": not repo.private,
                "error_code": None,
                "error_message": None,
            }
        except GithubException as error:
            if error.status == 404:
                return self._error(reference, "not_found", "Repository not found or inaccessible.")
            if error.status in {401, 403}:
                return self._error(reference, "access_denied", "GitHub access denied.")
            return self._error(
                reference, "github_error", "GitHub API returned an unexpected error."
            )

    @staticmethod
    def _error(reference: RepositoryReference, code: str, message: str) -> dict[str, object]:
        return {
            "success": False,
            "owner": reference.owner,
            "repo_name": reference.name,
            "full_name": reference.full_name,
            "canonical_url": reference.canonical_url,
            "is_public": False,
            "error_code": code,
            "error_message": message,
        }


repository_service = GitHubRepositoryService()
