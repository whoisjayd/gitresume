import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ContributionCommit:
    sha: str
    author: str
    author_email: str
    date: str
    subject: str
    files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContributionAnalysis:
    author: str
    days: int
    commits: list[ContributionCommit]
    touched_files: list[str]

    def to_prompt_context(self) -> str:
        header = f"git standup {self.author} -d {self.days}"
        if not self.commits:
            return f"{header}\nNo matching author commits were found."
        lines = [header, "", f"{len(self.commits)} matching commits"]
        for commit in self.commits:
            files = ", ".join(commit.files[:8])
            suffix = f" — {files}" if files else ""
            lines.append(f"- {commit.date} {commit.sha[:12]} {commit.subject}{suffix}")
        if self.touched_files:
            lines.extend(["", "Author-touched files:"])
            lines.extend(f"- {path}" for path in self.touched_files)
        return "\n".join(lines)


class ContributionAnalysisService:
    """Build a structured git-standup style contribution scope for one author."""

    def analyze(
        self,
        repo_root: str | Path,
        *,
        author: str,
        days: int,
        max_commits: int = 50,
        max_files: int = 200,
    ) -> ContributionAnalysis:
        root = Path(repo_root).resolve()
        clean_author = self._clean_author(author)
        author_prefilter = self._author_prefilter(clean_author)
        clean_days = max(1, min(days, 3650))
        clean_max_commits = max(1, min(max_commits, 500))
        clean_max_files = max(1, min(max_files, 2_000))
        command = [
            "git",
            "log",
            "--all",
            "--no-merges",
            "--regexp-ignore-case",
            f"--since={clean_days} days ago",
            f"--max-count={clean_max_commits}",
            "--format=%H%x00%an%x00%ae%x00%aI%x00%s",
            "--name-only",
            "--",
        ]
        if author_prefilter is not None:
            command.insert(6, f"--author={author_prefilter}")
        try:
            process = subprocess.run(
                command,
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ContributionAnalysis(clean_author, clean_days, [], [])
        if process.returncode != 0:
            return ContributionAnalysis(clean_author, clean_days, [], [])
        return self._parse_git_log(
            process.stdout,
            root=root,
            author=clean_author,
            days=clean_days,
            max_commits=clean_max_commits,
            max_files=clean_max_files,
        )

    def _parse_git_log(
        self,
        output: str,
        *,
        root: Path,
        author: str,
        days: int,
        max_commits: int,
        max_files: int,
    ) -> ContributionAnalysis:
        commits: list[ContributionCommit] = []
        touched: set[str] = set()
        current: dict[str, object] | None = None

        def flush_current() -> None:
            nonlocal current
            if current is None or len(commits) >= max_commits:
                current = None
                return
            raw_files = current.get("files", [])
            files = list(raw_files) if isinstance(raw_files, list) else []
            commits.append(
                ContributionCommit(
                    sha=str(current["sha"]),
                    author=str(current["author"]),
                    author_email=str(current["author_email"]),
                    date=str(current["date"]),
                    subject=str(current["subject"]),
                    files=files,
                )
            )
            current = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            header_parts = line.split("\x00", 4)
            if len(header_parts) == 5:
                flush_current()
                if len(commits) >= max_commits:
                    break
                if not self._author_matches_literal(header_parts[1], header_parts[2], author):
                    current = None
                    continue
                current = {
                    "sha": header_parts[0],
                    "author": header_parts[1],
                    "author_email": header_parts[2],
                    "date": header_parts[3],
                    "subject": header_parts[4],
                    "files": [],
                }
                continue
            if current is None or len(touched) >= max_files:
                continue
            safe_path = self._safe_existing_file(root, line)
            if safe_path is None:
                continue
            touched.add(safe_path)
            current_files = current["files"]
            if isinstance(current_files, list) and safe_path not in current_files:
                current_files.append(safe_path)
        flush_current()
        return ContributionAnalysis(
            author=author,
            days=days,
            commits=commits,
            touched_files=sorted(touched),
        )

    def _safe_existing_file(self, root: Path, relative_path: str) -> str | None:
        if not relative_path or relative_path.startswith(("/", "\\")):
            return None
        if ".." in relative_path.replace("\\", "/").split("/"):
            return None
        path = (root / relative_path).resolve()
        if path != root and root not in path.parents:
            return None
        if not path.is_file():
            return None
        return path.relative_to(root).as_posix()

    def _clean_author(self, author: str) -> str:
        cleaned = author.strip().lstrip("@")
        if not cleaned or "\x00" in cleaned:
            raise ValueError("analysis author must be non-empty and must not contain NUL bytes")
        return cleaned[:200]

    def _author_matches_literal(
        self, commit_author: str, commit_author_email: str, requested_author: str
    ) -> bool:
        normalized_commit_author = " ".join(commit_author.casefold().split())
        normalized_commit_author_email = " ".join(commit_author_email.casefold().split())
        normalized_requested_author = " ".join(requested_author.casefold().split())
        return (
            normalized_requested_author in normalized_commit_author
            or normalized_requested_author in normalized_commit_author_email
        )

    def _author_prefilter(self, author: str) -> str | None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]*", author):
            return author

        noreply_login = re.search(
            r"\b\d+\+([A-Za-z0-9-]+)@users\.noreply\.github\.com\b",
            author,
            flags=re.IGNORECASE,
        )
        if noreply_login is not None:
            return noreply_login.group(1)

        tokens = re.findall(r"[A-Za-z0-9]+", author)
        if not tokens:
            return None
        return max(tokens, key=len)
