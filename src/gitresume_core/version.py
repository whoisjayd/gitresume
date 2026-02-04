import subprocess

__version__ = "0.1.1"


def get_git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.STDOUT).decode().strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_tool_version() -> str:
    sha = get_git_sha()
    return f"{__version__} ({sha})"
