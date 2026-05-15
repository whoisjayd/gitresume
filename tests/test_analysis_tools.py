from pathlib import Path

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


def test_ai_tools_block_path_traversal(sample_repo: Path) -> None:
    outside = sample_repo.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    tools = RepositoryAnalysisTools(sample_repo)

    with pytest.raises(AnalysisToolError):
        tools.read("../outside.txt")
