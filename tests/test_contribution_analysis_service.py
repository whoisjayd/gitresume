from pathlib import Path
from types import SimpleNamespace

from gitresume.services.contribution_analysis_service import ContributionAnalysisService


def test_contribution_analysis_builds_bounded_git_standup_query(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 10
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "abc123\x00Jaydeep Solanki\x00jaydeep@example.com\x00"
                "2026-05-16T01:23:45+00:00\x00feat: add dashboard\n"
                "src/app.py\n"
                "README.md\n\n"
                "def456\x00Jaydeep Solanki\x00jaydeep@example.com\x00"
                "2026-05-15T09:00:00+00:00\x00fix: tests\n"
                "tests/test_app.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(
        tmp_path,
        author="Jaydeep Solanki",
        days=300,
        max_commits=10,
        max_files=20,
    )

    assert calls == [
        [
            "git",
            "log",
            "--all",
            "--no-merges",
            "--regexp-ignore-case",
            "--since=300 days ago",
            "--author=Jaydeep Solanki",
            "--max-count=10",
            "--format=%H%x00%an%x00%ae%x00%aI%x00%s",
            "--name-only",
            "--",
        ]
    ]
    assert [commit.subject for commit in analysis.commits] == [
        "feat: add dashboard",
        "fix: tests",
    ]
    assert analysis.touched_files == ["README.md", "src/app.py", "tests/test_app.py"]
    assert "git standup Jaydeep Solanki -d 300" in analysis.to_prompt_context()
    assert "src/app.py" in analysis.to_prompt_context()


def test_contribution_analysis_uses_safe_prefilter_token_for_regex_metacharacter_author(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    ContributionAnalysisService().analyze(tmp_path, author=".*", days=7)

    assert not any(part.startswith("--author=") for part in calls[0])


def test_contribution_analysis_prefilters_full_noreply_email_without_escaping_plus(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "owned.py").write_text("print('owned')\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "abc123\x00Some Name\x00123+octocat@users.noreply.github.com\x00"
                "2026-05-16T01:23:45+00:00\x00feat: owned\n"
                "src/owned.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(
        tmp_path,
        author="123+octocat@users.noreply.github.com",
        days=30,
    )

    author_filters = [part for part in calls[0] if part.startswith("--author=")]
    assert author_filters
    assert all("\\+" not in part for part in author_filters)
    assert [commit.author_email for commit in analysis.commits] == [
        "123+octocat@users.noreply.github.com"
    ]
    assert analysis.touched_files == ["src/owned.py"]


def test_contribution_analysis_filters_regex_like_author_results_literally(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alice.py").write_text("print('alice')\n", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "abc123\x00Alice\x00alice@example.com\x00"
                "2026-05-16T01:23:45+00:00\x00feat: alice work\n"
                "src/alice.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(tmp_path, author=".*", days=7)

    assert analysis.commits == []
    assert analysis.touched_files == []


def test_contribution_analysis_ignores_unsafe_and_untracked_paths(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "owned.py").write_text("print('owned')\n", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "abc123\x00Alice\x00alice@example.com\x002026-05-16T01:23:45+00:00\x00feat: owned\n"
                "src/owned.py\n"
                "../secret.txt\n"
                "missing.py\n"
                "/absolute/path.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(tmp_path, author="Alice", days=30)

    assert analysis.touched_files == ["src/owned.py"]


def test_contribution_analysis_matches_github_login_against_noreply_email(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "owned.py").write_text("print('owned')\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("print('other')\n", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "abc123\x00Some Name\x00123+octocat@users.noreply.github.com\x00"
                "2026-05-16T01:23:45+00:00\x00feat: owned\n"
                "src/owned.py\n\n"
                "def456\x00Other Person\x00other@example.com\x00"
                "2026-05-15T01:23:45+00:00\x00feat: other\n"
                "src/other.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(tmp_path, author="@octocat", days=30)

    assert [commit.author for commit in analysis.commits] == ["Some Name"]
    assert analysis.touched_files == ["src/owned.py"]


def test_contribution_analysis_returns_empty_on_git_failure(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del command, kwargs
        return SimpleNamespace(returncode=128, stdout="", stderr="not a git repository")

    monkeypatch.setattr("gitresume.services.contribution_analysis_service.subprocess.run", fake_run)

    analysis = ContributionAnalysisService().analyze(tmp_path, author="nobody", days=7)

    assert analysis.commits == []
    assert analysis.touched_files == []
    assert "No matching author commits" in analysis.to_prompt_context()
