import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gitresume.services.repository_service import parse_github_repository_url


@dataclass(frozen=True)
class RepositoryCheckout:
    local_path: Path
    owner: str
    name: str
    full_name: str
    canonical_url: str


class RepositoryCheckoutService:
    async def checkout(self, repo_url: str, github_token: str | None = None) -> RepositoryCheckout:
        reference = parse_github_repository_url(repo_url)
        local_path = Path(self._create_checkout_dir())
        clone_url = self._clone_url(reference.owner, reference.name)
        askpass_path: Path | None = None
        try:
            env = None
            if github_token:
                askpass_path = self._create_askpass_script()
                env = os.environ.copy()
                env.update(
                    {
                        "GIT_ASKPASS": str(askpass_path),
                        "GIT_TERMINAL_PROMPT": "0",
                        "GITRESUME_GITHUB_TOKEN": github_token,
                    }
                )
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                clone_url,
                str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await process.communicate()
            if askpass_path is not None:
                askpass_path.unlink(missing_ok=True)
                askpass_path = None
            if process.returncode == 0:
                return RepositoryCheckout(
                    local_path=local_path,
                    owner=reference.owner,
                    name=reference.name,
                    full_name=reference.full_name,
                    canonical_url=reference.canonical_url,
                )

            self.cleanup_path(local_path)
            message = stderr.decode(errors="replace").strip() or "Git clone failed."
            if github_token:
                message = message.replace(github_token, "[redacted]")
            raise RuntimeError(message)
        except Exception:
            if askpass_path is not None:
                askpass_path.unlink(missing_ok=True)
            self.cleanup_path(local_path)
            raise

    def cleanup_checkout(self, checkout: RepositoryCheckout) -> None:
        self.cleanup_path(checkout.local_path)

    def cleanup_path(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)

    def _create_checkout_dir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="gitresume-checkout-"))

    def _checkout_result(self, repo_url: str, local_path: Path) -> RepositoryCheckout:
        reference = parse_github_repository_url(repo_url)
        return RepositoryCheckout(
            local_path=local_path,
            owner=reference.owner,
            name=reference.name,
            full_name=reference.full_name,
            canonical_url=reference.canonical_url,
        )

    def _clone_url(self, owner: str, repo_name: str) -> str:
        return f"https://github.com/{owner}/{repo_name}.git"

    def _create_askpass_script(self) -> Path:
        suffix = ".cmd" if os.name == "nt" else ".sh"
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", prefix="gitresume-askpass-", suffix=suffix, delete=False
        )
        path = Path(handle.name)
        with handle:
            if os.name == "nt":
                python = sys.executable.replace('"', '\\"')
                python_code = (
                    "import os, sys; "
                    "print('x-access-token' if len(sys.argv) > 1 and "
                    "'Username' in sys.argv[1] else "
                    "os.environ.get('GITRESUME_GITHUB_TOKEN', ''))"
                )
                handle.write(f'@echo off\n@"{python}" -c "{python_code}" %*\n')
            else:
                handle.write(
                    "#!/bin/sh\n"
                    'case "$1" in\n'
                    "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
                    "  *) printf '%s\\n' \"$GITRESUME_GITHUB_TOKEN\" ;;\n"
                    "esac\n"
                )
        if os.name != "nt":
            path.chmod(0o700)
        return path
