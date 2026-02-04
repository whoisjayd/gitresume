"""
Provides tools for Git operations, primarily cloning repositories.

This module contains the high-level tool for cloning a Git repository
from a given URL into a local directory. It includes validation,
error handling, and performance optimizations for the cloning process.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from github import Github, GithubException

from .gitingest import IGNORE_DIRS, IGNORE_EXTENSIONS

logger = logging.getLogger(__name__)


def _parse_repo_url(repo_url: str) -> Tuple[str, str, str]:
    """Parses a repository URL to extract the owner and repo name."""
    try:
        parsed_url = urlparse(repo_url)
        path_parts = parsed_url.path.strip("/").replace(".git", "").split("/")
        if len(path_parts) < 2:
            raise ValueError("URL path does not contain owner/repo.")
        owner, repo_name = path_parts[:2]
        return owner, repo_name, f"{owner}/{repo_name}"
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid repository URL format: {repo_url}. Error: {e}")
        raise ValueError(f"Invalid repository URL format: {repo_url}") from e


async def _validate_git_install() -> None:
    """Checks if Git is installed and accessible."""
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            logger.debug(f"Git is installed: {stdout.decode().strip()}")
        else:
            raise FileNotFoundError(f"Git command failed: {stderr.decode()}")
    except FileNotFoundError as e:
        logger.error("Git is not installed or not in system PATH.")
        raise FileNotFoundError("Git not found. Please install it and ensure it's in your PATH.") from e


async def _check_github_access(repo_full_name: str, github_token: Optional[str]) -> bool:
    """Verifies access to the GitHub repository."""
    try:
        g = Github(github_token)
        repo = g.get_repo(repo_full_name)
        if repo.private and not github_token:
            logger.error(f"Repo '{repo_full_name}' is private but no token was provided.")
            raise PermissionError("Private repository requires a GitHub token for access.")
        logger.info(f"Successfully verified access to repo: {repo_full_name}")
        return not repo.private
    except GithubException as e:
        if e.status == 404:
            logger.error(f"Repository not found: {repo_full_name}")
            raise FileNotFoundError(f"Repository '{repo_full_name}' not found or you lack access.") from e
        elif e.status in [401, 403]:
            logger.error(f"Authentication error for repo: {repo_full_name}. Check your token.")
            raise PermissionError(f"Access denied for repo '{repo_full_name}'. Check token permissions.") from e
        else:
            logger.error(f"GitHub API error for '{repo_full_name}': {e}")
            raise IOError(f"Unable to access repository via GitHub API: {e}") from e


async def _run_clone_command(clone_url: str, repo_dir: Path) -> None:
    """Executes the git clone command in a subprocess."""
    args = [
        "git",
        "clone",
        "--depth",
        "1",  # Fetch only the latest commit
        "--filter=blob:none",  # Exclude file content initially
        "--no-checkout",  # Don't checkout files yet
        "--single-branch",
        clone_url,
        str(repo_dir),
    ]
    logger.info(f"Executing git clone for {repo_dir}...")
    process = await asyncio.create_subprocess_exec(*args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error(f"Git clone failed for '{repo_dir}'. Error: {error_msg}")
        raise IOError(f"Git clone failed: {error_msg}")

    logger.info(f"Sparse clone successful for {repo_dir}. Now checking out files...")

    # Now checkout the files
    process_checkout = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_dir),
        "checkout",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await process_checkout.communicate()
    if process_checkout.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error(f"Git checkout failed for '{repo_dir}'. Error: {error_msg}")
        raise IOError(f"Git checkout failed: {error_msg}")

    logger.info(f"Successfully cloned and checked out {repo_dir}")


def _get_repo_stats(repo_dir: Path) -> Tuple[int, int]:
    """
    Calculates the total size and file count of the repository,
    respecting the ignore rules from gitingest.
    """
    total_size = 0
    file_count = 0
    try:
        for root, dirs, files in os.walk(repo_dir):
            # Exclude ignored directories from traversal
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for filename in files:
                # Exclude ignored file extensions
                if Path(filename).suffix.lower() in IGNORE_EXTENSIONS:
                    continue

                file_path = Path(root) / filename
                total_size += file_path.stat().st_size
                file_count += 1
        return total_size, file_count
    except Exception as e:
        logger.error(f"Failed to calculate repo stats for '{repo_dir}': {e}")
        return 0, 0


async def clone_repo_tool(repo_url: str, target_dir: str, github_token: Optional[str] = None) -> Dict[str, any]:
    """
    Clones a GitHub repository to a specified local directory.

    This tool performs the following steps:
    1. Validates that Git is installed.
    2. Parses the repository URL.
    3. Checks if the repository already exists locally.
    4. Verifies access via the GitHub API.
    5. Clones the repository using optimized git commands.
    6. Returns statistics about the cloned repository.

    Args:
        repo_url: The full URL of the GitHub repository.
        target_dir: The base directory where the repo will be cloned.
        github_token: A GitHub personal access token for private repos.

    Returns:
        A dictionary with the operation's result, including local path,
        repo name, size, and file count on success, or an error message on failure.
    """
    try:
        await _validate_git_install()
        _, repo_name, repo_full_name = _parse_repo_url(repo_url)

        target_path = Path(target_dir)
        repo_dir = target_path / repo_name

        if repo_dir.exists() and (repo_dir / ".git").exists():
            logger.info(f"Repository '{repo_full_name}' already exists at '{repo_dir}'. Skipping clone.")
            repo_size_bytes, file_count = await asyncio.to_thread(_get_repo_stats, repo_dir)
            return {
                "success": True,
                "message": "Repository already cloned.",
                "local_path": str(repo_dir),
                "repo_name": repo_full_name,
                "repo_size_mb": round(repo_size_bytes / (1024 * 1024), 2),
                "file_count": file_count,
            }

        target_path.mkdir(parents=True, exist_ok=True)
        is_public = await _check_github_access(repo_full_name, github_token)

        clone_url = repo_url
        if not is_public and github_token:
            clone_url = f"https://oauth2:{github_token}@github.com/{repo_full_name}.git"

        await _run_clone_command(clone_url, repo_dir)

        repo_size_bytes, file_count = await asyncio.to_thread(_get_repo_stats, repo_dir)

        result = {
            "success": True,
            "message": "Repository cloned successfully.",
            "local_path": str(repo_dir),
            "repo_name": repo_full_name,
            "repo_size_mb": round(repo_size_bytes / (1024 * 1024), 2),
            "file_count": file_count,
        }
        logger.info(f"Clone successful: {result}")
        return result

    except (ValueError, FileNotFoundError, PermissionError, IOError) as e:
        logger.error(f"Clone failed for '{repo_url}'. Reason: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.critical(
            f"An unexpected error occurred during clone of '{repo_url}': {e}",
            exc_info=True,
        )
        return {"success": False, "error": f"An unexpected error occurred: {e}"}
