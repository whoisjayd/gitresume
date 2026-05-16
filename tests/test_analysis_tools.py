from pathlib import Path
from types import SimpleNamespace

import pytest

from gitresume.services.analysis_tools import AnalysisToolError, RepositoryAnalysisTools


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    return tmp_path


def test_ai_glob_returns_bounded_relative_matches(sample_repo: Path) -> None:
    tools = RepositoryAnalysisTools(sample_repo)

    assert tools.glob("**/*.py") == ["src/app.py"]


def test_ai_read_returns_requested_line_window(sample_repo: Path) -> None:
    tools = RepositoryAnalysisTools(sample_repo)

    result = tools.read("src/app.py", start_line=3, end_line=3)

    assert result.path == "src/app.py"
    assert result.start_line == 3
    assert result.end_line == 3
    assert result.content == "app = FastAPI()"


def test_ai_traverse_returns_directory_entries(sample_repo: Path) -> None:
    tools = RepositoryAnalysisTools(sample_repo)

    entries = tools.traverse(max_depth=1)

    assert "src/" in entries
    assert "src/app.py" in entries
    assert "README.md" in entries


def test_ai_rg_searches_repository_content(sample_repo: Path) -> None:
    tools = RepositoryAnalysisTools(sample_repo)

    matches = tools.rg("FastAPI", include_glob="*.py")

    assert [(match.path, match.line_number) for match in matches] == [
        ("src/app.py", 1),
        ("src/app.py", 3),
    ]


def test_ai_rg_python_fallback_treats_pattern_as_literal(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (sample_repo / "src" / "patterns.txt").write_text(
        "literal (a+)+$ pattern\nregular aaa\n", encoding="utf-8"
    )
    monkeypatch.setattr("gitresume.services.analysis_tools.shutil.which", lambda name: None)
    tools = RepositoryAnalysisTools(sample_repo)

    matches = tools.rg("(a+)+$", include_glob="**/*.txt")

    assert [(match.path, match.line_number, match.line) for match in matches] == [
        ("src/patterns.txt", 1, "literal (a+)+$ pattern")
    ]


def test_ai_rg_cli_uses_end_of_options_before_model_controlled_pattern(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    class FakePopen:
        returncode = 1
        stdout = iter(())
        stderr = SimpleNamespace(read=lambda: "")

        def __init__(self, command: list[str], **kwargs: object) -> None:
            del kwargs
            commands.append(command)

        def wait(self, timeout: int | None = None) -> int:
            del timeout
            return self.returncode

        def kill(self) -> None:
            raise AssertionError("process should not be killed for no matches")

    def fail_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        raise AssertionError("rg must stream output instead of capture_output=True")

    monkeypatch.setattr("gitresume.services.analysis_tools.shutil.which", lambda name: "rg")
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.run", fail_run)
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.Popen", FakePopen)
    tools = RepositoryAnalysisTools(sample_repo)

    assert tools.rg("-n", include_glob="*.py") == []

    assert commands[0][:5] == [
        "rg",
        "--line-number",
        "--with-filename",
        "--color=never",
        "--fixed-strings",
    ]
    assert "--" in commands[0]
    assert commands[0][commands[0].index("--") + 1] == "-n"


def test_ai_rg_cli_streams_and_terminates_after_max_matches(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines_read = 0

    class StreamingStdout:
        def __iter__(self) -> "StreamingStdout":
            return self

        def __next__(self) -> str:
            nonlocal lines_read
            lines_read += 1
            return f"src/app.py:{lines_read}:app = FastAPI()\n"

        def close(self) -> None:
            pass

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            del command, kwargs
            self.stdout = StreamingStdout()
            self.stderr = SimpleNamespace(read=lambda: "")
            self.returncode: int | None = None
            self.terminated = False
            created_processes.append(self)

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout: int | None = None) -> int:
            del timeout
            return self.returncode or 0

        def kill(self) -> None:
            raise AssertionError("terminate should stop the process before kill is needed")

    def fail_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        raise AssertionError(f"rg must not buffer output with subprocess.run: {command}")

    created_processes: list[FakePopen] = []
    monkeypatch.setattr("gitresume.services.analysis_tools.shutil.which", lambda name: "rg")
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.run", fail_run)
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.Popen", FakePopen)
    tools = RepositoryAnalysisTools(sample_repo)

    matches = tools.rg("FastAPI", include_glob="*.py", max_matches=3)

    assert len(matches) == 3
    assert lines_read == 3
    assert created_processes[0].terminated is True


def test_ai_rg_cli_kills_process_when_stdout_stream_exceeds_deadline(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BlockingStdout:
        def __iter__(self) -> "BlockingStdout":
            return self

        def __next__(self) -> str:
            raise TimeoutError("stdout read exceeded deadline")

        def close(self) -> None:
            pass

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            del command, kwargs
            self.stdout = BlockingStdout()
            self.stderr = SimpleNamespace(read=lambda: "")
            self.killed = False
            created_processes.append(self)

        def wait(self, timeout: int | None = None) -> int:
            del timeout
            return -9

        def terminate(self) -> None:
            raise AssertionError("streaming timeout should kill a hung ripgrep process")

        def kill(self) -> None:
            self.killed = True

    created_processes: list[FakePopen] = []
    monkeypatch.setattr("gitresume.services.analysis_tools.shutil.which", lambda name: "rg")
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.Popen", FakePopen)
    tools = RepositoryAnalysisTools(sample_repo)

    with pytest.raises(AnalysisToolError, match="timed out"):
        tools.rg("FastAPI", include_glob="*.py")

    assert created_processes[0].killed is True


def test_ai_rg_cli_kills_process_on_wait_timeout(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    class FakePopen:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            del command, kwargs
            self.stdout = iter(())
            self.stderr = SimpleNamespace(read=lambda: "")
            self.killed = False
            created_processes.append(self)

        def wait(self, timeout: int | float | None = None) -> int:
            if timeout is not None and timeout != 5:
                raise subprocess.TimeoutExpired(cmd="rg", timeout=timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    created_processes: list[FakePopen] = []
    monkeypatch.setattr("gitresume.services.analysis_tools.shutil.which", lambda name: "rg")
    monkeypatch.setattr("gitresume.services.analysis_tools.subprocess.Popen", FakePopen)
    tools = RepositoryAnalysisTools(sample_repo)

    with pytest.raises(AnalysisToolError, match="timed out"):
        tools.rg("FastAPI", include_glob="*.py")

    assert created_processes[0].killed is True


def test_ai_tools_can_be_limited_to_author_touched_files(sample_repo: Path) -> None:
    tools = RepositoryAnalysisTools(sample_repo, allowed_paths={"src/app.py"})

    assert tools.glob("**/*") == ["src/app.py"]
    assert tools.traverse() == ["src/", "src/app.py"]
    assert [(match.path, match.line_number) for match in tools.rg("FastAPI")] == [
        ("src/app.py", 1),
        ("src/app.py", 3),
    ]
    with pytest.raises(AnalysisToolError):
        tools.read("README.md")


def test_ai_tools_block_path_traversal(sample_repo: Path) -> None:
    outside = sample_repo.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    tools = RepositoryAnalysisTools(sample_repo)

    with pytest.raises(AnalysisToolError):
        tools.read("../outside.txt")
