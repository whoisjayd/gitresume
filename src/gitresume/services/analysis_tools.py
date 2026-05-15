import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AnalysisToolError(ValueError):
    """Raised when an analysis tool request is outside the repository boundary."""


@dataclass(frozen=True)
class FileReadResult:
    path: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True)
class SearchMatch:
    path: str
    line_number: int
    line: str


class RepositoryAnalysisTools:
    """Safe, project-bounded tools for multi-step AI repository analysis."""

    def __init__(self, repository_root: str | Path) -> None:
        self.root = Path(repository_root).resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise AnalysisToolError("Repository root must be an existing directory.")

    def glob(self, pattern: str, *, limit: int = 200) -> list[str]:
        matches = []
        for path in self.root.glob(pattern):
            resolved = self._ensure_inside_root(path)
            if resolved.is_file():
                matches.append(self._relative(resolved))
            if len(matches) >= limit:
                break
        return sorted(matches)

    def traverse(self, path: str = ".", *, max_depth: int = 2, limit: int = 500) -> list[str]:
        start = self._ensure_inside_root(self.root / path)
        entries: list[str] = []

        def walk(current: Path, depth: int) -> None:
            if depth > max_depth or len(entries) >= limit:
                return
            for child in sorted(
                current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
            ):
                if child.name in {".git", ".venv", "node_modules", "__pycache__"}:
                    continue
                resolved = self._ensure_inside_root(child)
                suffix = "/" if resolved.is_dir() else ""
                entries.append(f"{self._relative(resolved)}{suffix}")
                if resolved.is_dir():
                    walk(resolved, depth + 1)
                if len(entries) >= limit:
                    return

        walk(start, 0)
        return entries

    def read(
        self,
        path: str,
        *,
        start_line: int = 1,
        end_line: int | None = None,
        max_chars: int = 20_000,
    ) -> FileReadResult:
        file_path = self._ensure_inside_root(self.root / path)
        if not file_path.is_file():
            raise AnalysisToolError("Path must point to a file inside the repository.")
        if start_line < 1:
            raise AnalysisToolError("start_line must be greater than zero.")

        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        requested_end = end_line or len(lines)
        if requested_end < start_line:
            raise AnalysisToolError("end_line must be greater than or equal to start_line.")

        selected = lines[start_line - 1 : requested_end]
        content = "\n".join(selected)
        if len(content) > max_chars:
            content = content[:max_chars]
        actual_end = min(requested_end, len(lines))
        return FileReadResult(
            path=self._relative(file_path),
            start_line=start_line,
            end_line=actual_end,
            content=content,
        )

    def rg(
        self,
        pattern: str,
        *,
        include_glob: str | None = None,
        max_matches: int = 100,
    ) -> list[SearchMatch]:
        if shutil.which("rg"):
            return self._ripgrep(pattern, include_glob=include_glob, max_matches=max_matches)
        return self._python_search(pattern, include_glob=include_glob, max_matches=max_matches)

    def _ripgrep(
        self,
        pattern: str,
        *,
        include_glob: str | None,
        max_matches: int,
    ) -> list[SearchMatch]:
        command = ["rg", "--line-number", "--color=never", pattern]
        if include_glob:
            command.extend(["--glob", include_glob])
        process = subprocess.run(
            command,
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if process.returncode not in {0, 1}:
            raise AnalysisToolError(process.stderr.strip() or "ripgrep failed.")

        matches: list[SearchMatch] = []
        for line in process.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            file_path, line_number, text = parts
            resolved = self._ensure_inside_root(self.root / file_path)
            matches.append(SearchMatch(self._relative(resolved), int(line_number), text))
            if len(matches) >= max_matches:
                break
        return matches

    def _python_search(
        self,
        pattern: str,
        *,
        include_glob: str | None,
        max_matches: int,
    ) -> list[SearchMatch]:
        regex = re.compile(pattern)
        files = self.glob(include_glob or "**/*", limit=5_000)
        matches: list[SearchMatch] = []
        for relative_path in files:
            file_path = self._ensure_inside_root(self.root / relative_path)
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
            ):
                if regex.search(line):
                    matches.append(SearchMatch(relative_path, line_number, line))
                if len(matches) >= max_matches:
                    return matches
        return matches

    def _ensure_inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise AnalysisToolError("Path escapes repository boundary.")
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()
