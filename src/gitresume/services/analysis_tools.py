import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import NoReturn


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

    def __init__(
        self, repository_root: str | Path, *, allowed_paths: set[str] | None = None
    ) -> None:
        self.root = Path(repository_root).resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise AnalysisToolError("Repository root must be an existing directory.")
        self.allowed_paths = self._normalize_allowed_paths(allowed_paths)

    def glob(self, pattern: str, *, limit: int = 200) -> list[str]:
        matches = []
        for path in self.root.glob(pattern):
            resolved = self._ensure_inside_root(path)
            if resolved.is_file() and self._is_allowed(resolved):
                matches.append(self._relative(resolved))
            if len(matches) >= limit:
                break
        return sorted(matches)

    def traverse(self, path: str = ".", *, max_depth: int = 2, limit: int = 500) -> list[str]:
        start = self._ensure_inside_root(self.root / path)
        if self.allowed_paths is not None:
            return self._traverse_allowed(start, max_depth=max_depth, limit=limit)
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
        if not self._is_allowed(file_path):
            raise AnalysisToolError("Path is outside the configured analysis scope.")
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
        command = [
            "rg",
            "--line-number",
            "--with-filename",
            "--color=never",
            "--fixed-strings",
        ]
        if include_glob:
            command.extend(["--glob", include_glob])
        command.extend(["--", pattern])
        if self.allowed_paths is not None:
            scoped_paths = self._allowed_paths_matching(include_glob)
            if not scoped_paths:
                return []
            command.extend(scoped_paths)
        process = subprocess.Popen(
            command,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        matches: list[SearchMatch] = []
        terminated_after_limit = False
        timeout_seconds = 15.0
        deadline = time.monotonic() + timeout_seconds
        stdout_queue: queue.Queue[object] = queue.Queue(maxsize=max(1, max_matches))
        stream_done = object()
        read_permit = threading.Semaphore(1)
        stop_reading = threading.Event()

        def read_stdout() -> None:
            try:
                if process.stdout is not None:
                    stdout_iterator = iter(process.stdout)
                    while not stop_reading.is_set():
                        read_permit.acquire()
                        if stop_reading.is_set():
                            break
                        try:
                            stdout_queue.put(next(stdout_iterator))
                        except StopIteration:
                            break
            except BaseException as error:  # noqa: BLE001 - shuttle reader failures to main thread
                stdout_queue.put(error)
            finally:
                stdout_queue.put(stream_done)

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stdout_thread.start()

        def kill_timed_out_process(error: BaseException) -> NoReturn:
            stop_reading.set()
            read_permit.release()
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise AnalysisToolError("ripgrep timed out.") from error

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    kill_timed_out_process(subprocess.TimeoutExpired(command, timeout_seconds))
                try:
                    item = stdout_queue.get(timeout=min(0.05, remaining))
                except queue.Empty:
                    continue
                if item is stream_done:
                    break
                if isinstance(item, BaseException):
                    kill_timed_out_process(item)
                line = item
                if not isinstance(line, str):
                    read_permit.release()
                    continue
                parts = line.rstrip("\n").split(":", 2)
                if len(parts) != 3:
                    read_permit.release()
                    continue
                file_path, line_number, text = parts
                resolved = self._ensure_inside_root(self.root / file_path)
                matches.append(SearchMatch(self._relative(resolved), int(line_number), text))
                if len(matches) >= max_matches:
                    terminated_after_limit = True
                    stop_reading.set()
                    process.terminate()
                    break
                read_permit.release()
            remaining = max(0.01, deadline - time.monotonic())
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            kill_timed_out_process(error)
        finally:
            if process.stdout is not None and hasattr(process.stdout, "close"):
                process.stdout.close()

        if returncode not in {0, 1} and not terminated_after_limit:
            stderr = process.stderr.read().strip() if process.stderr is not None else ""
            raise AnalysisToolError(stderr or "ripgrep failed.")
        return matches

    def _python_search(
        self,
        pattern: str,
        *,
        include_glob: str | None,
        max_matches: int,
    ) -> list[SearchMatch]:
        files = (
            self._allowed_paths_matching(include_glob)
            if self.allowed_paths is not None
            else self.glob(include_glob or "**/*", limit=5_000)
        )
        matches: list[SearchMatch] = []
        for relative_path in files:
            file_path = self._ensure_inside_root(self.root / relative_path)
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
            ):
                if pattern in line:
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

    def _normalize_allowed_paths(self, allowed_paths: set[str] | None) -> set[str] | None:
        if allowed_paths is None:
            return None
        normalized: set[str] = set()
        for item in allowed_paths:
            path = self._ensure_inside_root(self.root / item)
            if path.is_file():
                normalized.add(self._relative(path))
        return normalized

    def _is_allowed(self, path: Path) -> bool:
        if self.allowed_paths is None:
            return True
        return self._relative(path) in self.allowed_paths

    def _allowed_paths_matching(self, include_glob: str | None) -> list[str]:
        if self.allowed_paths is None:
            return []
        if include_glob is None or include_glob == "**/*":
            return sorted(self.allowed_paths)
        pattern = include_glob or "**/*"
        return sorted(path for path in self.allowed_paths if fnmatch(path, pattern))

    def _traverse_allowed(self, start: Path, *, max_depth: int, limit: int) -> list[str]:
        assert self.allowed_paths is not None
        entries: set[str] = set()
        start_relative = "." if start == self.root else self._relative(start)
        for allowed in sorted(self.allowed_paths):
            allowed_path = Path(allowed)
            if start_relative != "." and not (
                allowed == start_relative or allowed.startswith(f"{start_relative}/")
            ):
                continue
            parts = allowed_path.parts
            for index in range(len(parts)):
                candidate = "/".join(parts[: index + 1])
                depth = index
                if depth > max_depth:
                    continue
                resolved = self._ensure_inside_root(self.root / candidate)
                suffix = "/" if resolved.is_dir() else ""
                entries.add(f"{candidate}{suffix}")
                if len(entries) >= limit:
                    return sorted(entries)
        return sorted(entries)
