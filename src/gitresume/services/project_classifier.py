import json
from dataclasses import dataclass, field
from pathlib import Path

from gitresume.services.analysis_tools import RepositoryAnalysisTools

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".pyi": "python",
    ".ipynb": "python-notebook",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".php": "php",
    ".rb": "ruby",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".swift": "swift",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
}

LANGUAGE_RELEVANT_GLOBS = {
    "python": ["src/**/*.py", "app/**/*.py", "*.py", "tests/**/*.py"],
    "python-notebook": ["**/*.ipynb"],
    "javascript": ["src/**/*.{js,jsx,mjs,cjs}", "frontend/src/**/*.{js,jsx,mjs,cjs}"],
    "typescript": ["src/**/*.{ts,tsx,mts,cts}", "frontend/src/**/*.{ts,tsx,mts,cts}"],
    "java": ["src/**/*.java", "app/**/*.java", "**/src/main/java/**/*.java"],
    "go": ["**/*.go", "go.mod"],
    "rust": ["src/**/*.rs", "Cargo.toml"],
    "c": ["**/*.{c,h}"],
    "cpp": ["**/*.{cpp,cc,cxx,hpp,hh}"],
    "csharp": ["**/*.cs", "**/*.csproj", "*.sln"],
    "kotlin": ["**/*.{kt,kts}"],
    "php": ["**/*.php", "composer.json"],
    "ruby": ["**/*.rb", "Gemfile", "*.gemspec"],
    "sql": ["**/*.sql"],
    "html": ["**/*.{html,htm}"],
    "css": ["**/*.{css,scss,sass}"],
    "markdown": ["README.md", "docs/**/*.md", "**/*.mdx"],
    "yaml": ["**/*.{yaml,yml}"],
    "json": ["**/*.json"],
    "shell": ["**/*.{sh,bash,zsh}"],
    "powershell": ["**/*.ps1"],
    "swift": ["**/*.swift"],
    "scala": ["**/*.scala"],
    "r": ["**/*.r"],
    "lua": ["**/*.lua"],
    "elixir": ["**/*.{ex,exs}"],
}


@dataclass(frozen=True)
class ProjectProfile:
    project_type: str
    languages: list[str]
    frameworks: list[str]
    package_managers: list[str]
    entrypoint_hints: list[str] = field(default_factory=list)
    relevant_globs: list[str] = field(default_factory=list)


class ProjectClassifier:
    """Infer project shape before selecting files for resume generation."""

    def __init__(self, repository_root: str | Path) -> None:
        self.root = Path(repository_root).resolve()
        self.tools = RepositoryAnalysisTools(self.root)

    def classify(self) -> ProjectProfile:
        files = set(self.tools.glob("**/*", limit=10_000))
        languages = self._languages(files)
        package_managers = self._package_managers(files)
        frameworks = self._frameworks(files)
        project_type = self._project_type(files, frameworks)
        entrypoints = self._entrypoints(files)
        relevant_globs = self._relevant_globs(project_type, languages)
        return ProjectProfile(
            project_type=project_type,
            languages=languages,
            frameworks=frameworks,
            package_managers=package_managers,
            entrypoint_hints=entrypoints,
            relevant_globs=relevant_globs,
        )

    def _languages(self, files: set[str]) -> list[str]:
        languages = {
            LANGUAGE_EXTENSIONS[Path(file).suffix.lower()]
            for file in files
            if Path(file).suffix.lower() in LANGUAGE_EXTENSIONS
        }
        return sorted(languages)

    def _package_managers(self, files: set[str]) -> list[str]:
        managers = []
        if "pyproject.toml" in files or "uv.lock" in files:
            managers.append("uv")
        if "requirements.txt" in files:
            managers.append("pip")
        if "package.json" in files:
            managers.append("npm")
        if "pnpm-lock.yaml" in files:
            managers.append("pnpm")
        if "bun.lock" in files or "bun.lockb" in files:
            managers.append("bun")
        return managers

    def _frameworks(self, files: set[str]) -> list[str]:
        frameworks = set()
        package_json = self._read_json("package.json")
        dependencies = {}
        if package_json:
            package_dependencies = package_json.get("dependencies", {})
            package_dev_dependencies = package_json.get("devDependencies", {})
            if isinstance(package_dependencies, dict):
                dependencies.update(package_dependencies)
            if isinstance(package_dev_dependencies, dict):
                dependencies.update(package_dev_dependencies)
        if "react" in dependencies:
            frameworks.add("react")
        if "vite" in dependencies or "vite.config.ts" in files or "vite.config.js" in files:
            frameworks.add("vite")
        if "next" in dependencies:
            frameworks.add("nextjs")
        if "@angular/core" in dependencies:
            frameworks.add("angular")
        if "vue" in dependencies:
            frameworks.add("vue")
        if "svelte" in dependencies:
            frameworks.add("svelte")

        python_text = self._read_text("pyproject.toml") + "\n" + self._read_text("requirements.txt")
        python_text_lower = python_text.lower()
        if "fastapi" in python_text_lower:
            frameworks.add("fastapi")
        if "django" in python_text_lower:
            frameworks.add("django")
        if "flask" in python_text_lower:
            frameworks.add("flask")
        if "litellm" in python_text_lower:
            frameworks.add("litellm")
        if (
            "spring-boot" in self._read_text("pom.xml").lower()
            or "springboot" in self._read_text("build.gradle").lower()
        ):
            frameworks.add("spring-boot")
        if "actix" in self._read_text("Cargo.toml").lower():
            frameworks.add("actix")
        if "gin-gonic" in self._read_text("go.mod").lower():
            frameworks.add("gin")
        return sorted(frameworks)

    def _project_type(self, files: set[str], frameworks: list[str]) -> str:
        has_frontend = (
            "react" in frameworks or "vite" in frameworks or "frontend/package.json" in files
        )
        has_api = "fastapi" in frameworks or any(file.endswith("main.py") for file in files)
        if has_api and has_frontend:
            return "fullstack-web-app"
        if has_api:
            return "backend-api"
        if has_frontend:
            return "frontend-app"
        if "pyproject.toml" in files:
            return "python-package"
        if "package.json" in files:
            return "node-package"
        return "unknown"

    def _entrypoints(self, files: set[str]) -> list[str]:
        names = {
            "app.py",
            "main.py",
            "src/main.py",
            "src/app.py",
            "src/main.tsx",
            "src/App.tsx",
            "frontend/src/main.tsx",
            "frontend/src/App.tsx",
            "Dockerfile",
            "Containerfile",
            "docker-compose.yml",
            "compose.yml",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "composer.json",
            "Gemfile",
        }
        return sorted(file for file in files if file in names or Path(file).name in names)

    def _relevant_globs(self, project_type: str, languages: list[str]) -> list[str]:
        globs = [
            "README.md",
            "pyproject.toml",
            "package.json",
            "Dockerfile",
            "compose.yml",
            "docker-compose.yml",
        ]
        for language in languages:
            globs.extend(LANGUAGE_RELEVANT_GLOBS.get(language, []))
        if project_type == "fullstack-web-app":
            globs.extend(["frontend/package.json", "frontend/vite.config.*", "src/**/routes/*.py"])
        return globs

    def _read_text(self, path: str) -> str:
        try:
            return self.tools.read(path, max_chars=60_000).content
        except Exception:
            return ""

    def _read_json(self, path: str) -> dict[str, object]:
        try:
            return json.loads(self._read_text(path))
        except (json.JSONDecodeError, TypeError):
            return {}
