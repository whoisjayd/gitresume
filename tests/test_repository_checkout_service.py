from pathlib import Path

import pytest

from gitresume.services.repository_checkout_service import RepositoryCheckoutService


@pytest.mark.asyncio
async def test_checkout_uses_askpass_token_without_token_in_clone_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> FakeProcess:
        commands.append(command)
        environments.append(kwargs["env"])  # type: ignore[arg-type]
        return FakeProcess()

    monkeypatch.setattr(
        "gitresume.services.repository_checkout_service.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    service = RepositoryCheckoutService()
    checkout = await service.checkout(
        "https://github.com/example/project", github_token="secret-token"
    )

    assert commands == [
        (
            "git",
            "clone",
            "--depth",
            "1",
            "https://github.com/example/project.git",
            str(checkout.local_path),
        )
    ]
    assert environments[0]["GIT_TERMINAL_PROMPT"] == "0"
    assert environments[0]["GITRESUME_GITHUB_TOKEN"] == "secret-token"
    assert checkout.owner == "example"
    assert checkout.name == "project"
    assert checkout.full_name == "example/project"
    assert checkout.canonical_url == "https://github.com/example/project"
    assert "secret-token" not in str(checkout)
    service.cleanup_checkout(checkout)


@pytest.mark.asyncio
async def test_checkout_sanitizes_token_from_failed_clone_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "checkout"
    temp_dir.mkdir()

    class FakeProcess:
        returncode = 128

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"fatal: Authentication failed for secret-token"

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> FakeProcess:
        assert "secret-token" not in " ".join(command)
        assert kwargs["env"]["GITRESUME_GITHUB_TOKEN"] == "secret-token"  # type: ignore[index]
        return FakeProcess()

    service = RepositoryCheckoutService()
    monkeypatch.setattr(service, "_create_checkout_dir", lambda: temp_dir)
    monkeypatch.setattr(
        "gitresume.services.repository_checkout_service.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(RuntimeError) as exc_info:
        await service.checkout("https://github.com/example/project", github_token="secret-token")

    assert "secret-token" not in str(exc_info.value)
    assert not temp_dir.exists()


def test_checkout_cleanup_removes_managed_temp_directory() -> None:
    service = RepositoryCheckoutService()
    temp_dir = Path(service._create_checkout_dir())
    checkout = service._checkout_result(
        repo_url="https://github.com/example/project",
        local_path=temp_dir,
    )
    (temp_dir / "marker.txt").write_text("cloned", encoding="utf-8")

    service.cleanup_checkout(checkout)

    assert not temp_dir.exists()


def test_windows_askpass_script_does_not_expand_token_in_cmd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RepositoryCheckoutService()
    monkeypatch.setattr("gitresume.services.repository_checkout_service.os.name", "nt")

    askpass_path = service._create_askpass_script()
    try:
        script = askpass_path.read_text(encoding="utf-8")
    finally:
        askpass_path.unlink(missing_ok=True)

    assert "%GITRESUME_GITHUB_TOKEN%" not in script
    assert "os.environ" in script


@pytest.mark.asyncio
async def test_checkout_cleans_temp_directory_when_git_launch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "checkout"
    temp_dir.mkdir()

    async def fail_create_subprocess_exec(*command: str, **kwargs: object) -> object:
        del command, kwargs
        raise FileNotFoundError("git missing")

    service = RepositoryCheckoutService()
    monkeypatch.setattr(service, "_create_checkout_dir", lambda: temp_dir)
    monkeypatch.setattr(
        "gitresume.services.repository_checkout_service.asyncio.create_subprocess_exec",
        fail_create_subprocess_exec,
    )

    with pytest.raises(FileNotFoundError, match="git missing"):
        await service.checkout("https://github.com/example/project")

    assert not temp_dir.exists()
