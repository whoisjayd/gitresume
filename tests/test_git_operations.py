from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gitresume_core.git_operations import _get_repo_stats, _parse_repo_url, clone_repo_tool


def test_parse_repo_url():
    owner, repo, full_name = _parse_repo_url("https://github.com/owner/repo.git")
    assert owner == "owner"
    assert repo == "repo"
    assert full_name == "owner/repo"

    owner, repo, full_name = _parse_repo_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"
    assert full_name == "owner/repo"


def test_parse_repo_url_invalid():
    with pytest.raises(ValueError, match="Invalid repository URL format"):
        _parse_repo_url("invalid-url")


def test_get_repo_stats(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file1.py").write_text("print('hello')")
    (repo_dir / "file2.txt").write_text("text")  # .txt is ignored
    (repo_dir / ".git").mkdir()
    (repo_dir / ".git" / "config").write_text("config")  # .git is ignored

    size, count = _get_repo_stats(repo_dir)
    assert count == 1
    assert size > 0


@pytest.mark.asyncio
async def test_validate_git_install_success():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"git version 2.0.0", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        from gitresume_core.git_operations import _validate_git_install

        await _validate_git_install()
        mock_exec.assert_called_once_with("git", "--version", stdout=-1, stderr=-1)


@pytest.mark.asyncio
async def test_validate_git_install_fail():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = FileNotFoundError()
        from gitresume_core.git_operations import _validate_git_install

        with pytest.raises(FileNotFoundError, match="Git not found"):
            await _validate_git_install()


@pytest.mark.asyncio
@patch("gitresume_core.git_operations.Github")
async def test_check_github_access_public(mock_github_class):
    mock_github_instance = mock_github_class.return_value
    mock_repo = MagicMock()
    mock_repo.private = False
    mock_github_instance.get_repo.return_value = mock_repo

    from gitresume_core.git_operations import _check_github_access

    is_public = await _check_github_access("owner/repo", None)
    assert is_public is True


@pytest.mark.asyncio
@patch("gitresume_core.git_operations.Github")
async def test_check_github_access_private_no_token(mock_github_class):
    mock_github_instance = mock_github_class.return_value
    mock_repo = MagicMock()
    mock_repo.private = True
    mock_github_instance.get_repo.return_value = mock_repo

    from gitresume_core.git_operations import _check_github_access

    with pytest.raises(PermissionError, match="Private repository requires a GitHub token"):
        await _check_github_access("owner/repo", None)


@pytest.mark.asyncio
async def test_run_clone_command_success(tmp_path):
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        from gitresume_core.git_operations import _run_clone_command

        await _run_clone_command("http://url", tmp_path / "repo")
        assert mock_exec.call_count == 2  # clone and checkout


@pytest.mark.asyncio
@patch("gitresume_core.git_operations.Github")
async def test_check_github_access_not_found(mock_github_class):
    from github import GithubException

    mock_github_instance = mock_github_class.return_value
    mock_github_instance.get_repo.side_effect = GithubException(404, {"message": "Not Found"}, {})

    from gitresume_core.git_operations import _check_github_access

    with pytest.raises(FileNotFoundError, match="not found or you lack access"):
        await _check_github_access("owner/repo", None)


@pytest.mark.asyncio
@patch("gitresume_core.git_operations.Github")
async def test_check_github_access_auth_error(mock_github_class):
    from github import GithubException

    mock_github_instance = mock_github_class.return_value
    mock_github_instance.get_repo.side_effect = GithubException(401, {"message": "Bad credentials"}, {})

    from gitresume_core.git_operations import _check_github_access

    with pytest.raises(PermissionError, match="Check token permissions"):
        await _check_github_access("owner/repo", "bad-token")


@pytest.mark.asyncio
async def test_run_clone_command_fail():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"Clone failed")
        mock_process.returncode = 1
        mock_exec.return_value = mock_process

        from gitresume_core.git_operations import _run_clone_command

        with pytest.raises(IOError, match="Git clone failed"):
            await _run_clone_command("http://url", Path("/tmp/repo"))


@pytest.mark.asyncio
@patch("gitresume_core.git_operations._validate_git_install", new_callable=AsyncMock)
@patch("gitresume_core.git_operations._check_github_access", new_callable=AsyncMock)
@patch("gitresume_core.git_operations._run_clone_command", new_callable=AsyncMock)
async def test_clone_repo_tool_already_exists(mock_clone, mock_access, mock_validate, tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    (repo_dir / "main.py").write_text("print('hi')")

    repo_url = "https://github.com/owner/repo"
    # Target dir should be tmp_path
    result = await clone_repo_tool(repo_url, str(tmp_path))

    assert result["success"] is True
    assert "already cloned" in result["message"]
    assert result["file_count"] == 1
    mock_clone.assert_not_called()


@pytest.mark.asyncio
@patch("gitresume_core.git_operations._validate_git_install", new_callable=AsyncMock)
@patch("gitresume_core.git_operations._check_github_access", new_callable=AsyncMock)
@patch("gitresume_core.git_operations._run_clone_command", new_callable=AsyncMock)
async def test_clone_repo_tool_full_clone(mock_clone, mock_access, mock_validate, tmp_path):
    mock_access.return_value = True  # public
    repo_url = "https://github.com/owner/new-repo"

    # We need to simulate the creation of the dir by mock_clone for stats to work
    repo_dir = tmp_path / "new-repo"

    async def side_effect(*args, **kwargs):
        repo_dir.mkdir()
        (repo_dir / "file.py").write_text("print(1)")

    mock_clone.side_effect = side_effect

    result = await clone_repo_tool(repo_url, str(tmp_path))

    assert result["success"] is True
    assert "cloned successfully" in result["message"]
    assert result["file_count"] == 1
    mock_clone.assert_called_once()
