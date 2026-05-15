from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from gitresume.services.analysis_tools import RepositoryAnalysisTools
from gitresume.services.project_classifier import LANGUAGE_EXTENSIONS, ProjectProfile

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    ".turbo",
    "target",
    "vendor",
}

DEFAULT_IGNORE_GLOBS = {
    "*.lock",
    "*.min.js",
    "*.map",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.sqlite",
    "*.db",
    ".env*",
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    "**/uv.lock",
}

CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".sql",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".kts",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    ".swift",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".lua",
    ".ex",
    ".exs",
    ".r",
}

CONFIG_EXTENSIONS = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}

HIGH_VALUE_NAMES = {
    "app.py",
    "main.py",
    "server.py",
    "router.py",
    "routes.py",
    "service.py",
    "services.py",
    "models.py",
    "schemas.py",
    "pyproject.toml",
    "package.json",
    "dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "containerfile",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "composer.json",
    "gemfile",
}

HIGH_VALUE_PATH_PARTS = {
    "api",
    "routes",
    "services",
    "core",
    "domain",
    "models",
    "schemas",
    "lib",
    "src",
    "app",
    "server",
    "infra",
    "workers",
    "jobs",
    "components",
    "pages",
    "controllers",
    "handlers",
    "middleware",
    "cmd",
    "internal",
    "pkg",
    "contracts",
    "migrations",
}

RESUME_KEYWORDS = {
    "fastapi",
    "react",
    "vite",
    "docker",
    "redis",
    "oauth",
    "auth",
    "api",
    "async",
    "websocket",
    "database",
    "cache",
    "queue",
    "worker",
    "service",
    "repository",
    "pipeline",
    "provider",
    "security",
    "test",
    "deploy",
    "kubernetes",
    "graphql",
    "grpc",
    "spring",
    "django",
    "flask",
    "gin",
    "actix",
    "rails",
    "laravel",
}


@dataclass(frozen=True)
class RankedFile:
    path: str
    score: int
    reasons: list[str] = field(default_factory=list)


class RankedContextBuilder:
    """Select the most resume-relevant code before AI generation."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        project_profile: ProjectProfile | None = None,
        ignore_dirs: set[str] | None = None,
        ignore_globs: set[str] | None = None,
    ) -> None:
        self.root = Path(repository_root).resolve()
        self.tools = RepositoryAnalysisTools(self.root)
        self.project_profile = project_profile
        self.ignore_dirs = DEFAULT_IGNORE_DIRS | (ignore_dirs or set())
        self.ignore_globs = DEFAULT_IGNORE_GLOBS | (ignore_globs or set())

    def rank_files(self, *, limit: int = 40) -> list[RankedFile]:
        ranked: list[RankedFile] = []
        for relative_path in self.tools.glob("**/*", limit=10_000):
            if self._ignored(relative_path):
                continue
            ranked_file = self._score(relative_path)
            if ranked_file.score > 0:
                ranked.append(ranked_file)

        ranked.sort(key=lambda item: (-item.score, item.path))
        return ranked[:limit]

    def build_ranked_context(
        self,
        *,
        file_limit: int = 20,
        max_chars_per_file: int = 8_000,
    ) -> str:
        sections = []
        for item in self.rank_files(limit=file_limit):
            result = self.tools.read(item.path, max_chars=max_chars_per_file)
            sections.append(
                f"## {item.path}\n"
                f"Score: {item.score}\n"
                f"Reasons: {', '.join(item.reasons)}\n"
                f"```\n{result.content}\n```"
            )
        return "\n\n".join(sections)

    def selected_file_paths(self, *, limit: int = 20) -> list[str]:
        return [item.path for item in self.rank_files(limit=limit)]

    def _ignored(self, relative_path: str) -> bool:
        path = Path(relative_path)
        if any(part in self.ignore_dirs for part in path.parts):
            return True
        return any(fnmatch(relative_path, pattern) for pattern in self.ignore_globs)

    def _score(self, relative_path: str) -> RankedFile:
        path = Path(relative_path)
        name = path.name.lower()
        suffix = path.suffix.lower()
        parts = {part.lower() for part in path.parts}
        score = 0
        reasons: list[str] = []

        if suffix in CODE_EXTENSIONS:
            score += 40
            reasons.append("source code")
        elif suffix in CONFIG_EXTENSIONS:
            score += 18
            reasons.append("configuration")
        elif name in {"readme.md", "architecture.md"}:
            score += 16
            reasons.append("project documentation")

        if name in HIGH_VALUE_NAMES:
            score += 25
            reasons.append("high-value entry/config file")

        if self.project_profile and relative_path in self.project_profile.entrypoint_hints:
            score += 35
            reasons.append("classified project entrypoint")

        if self.project_profile and suffix.lstrip(".") in self._profile_language_extensions():
            score += 12
            reasons.append("matches classified project language")

        high_value_parts = parts & HIGH_VALUE_PATH_PARTS
        if high_value_parts:
            score += min(24, len(high_value_parts) * 8)
            reasons.append("high-value path")

        if "test" in name or "tests" in parts:
            score += 10
            reasons.append("testing evidence")

        try:
            sample = (self.root / relative_path).read_text(encoding="utf-8", errors="ignore")[
                :12_000
            ]
        except OSError:
            sample = ""
        keyword_hits = {keyword for keyword in RESUME_KEYWORDS if keyword in sample.lower()}
        if keyword_hits:
            score += min(30, len(keyword_hits) * 3)
            reasons.append("resume-relevant implementation terms")

        return RankedFile(path=relative_path, score=score, reasons=reasons)

    def _profile_language_extensions(self) -> set[str]:
        if not self.project_profile:
            return set()
        extension_by_language = {
            language: {
                extension.removeprefix(".")
                for extension, mapped in LANGUAGE_EXTENSIONS.items()
                if mapped == language
            }
            for language in set(LANGUAGE_EXTENSIONS.values())
        }
        extensions: set[str] = set()
        for language in self.project_profile.languages:
            extensions.update(extension_by_language.get(language, set()))
        return extensions
