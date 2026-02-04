import pytest
import json
from typer.testing import CliRunner
from gitresume_cli.main import app
from unittest.mock import patch, MagicMock

runner = CliRunner()

@patch("gitresume_core.gitingest.gitingest_tool")
@patch("gitresume_core.create_resume.generate_resume_from_data")
def test_full_flow_analyze_then_generate(mock_generate, mock_gitingest, temp_artifact_dir):
    """Test the full flow: analyze a repo, then generate a resume from the artifacts."""

    # 1. Setup Mock Analysis (async functions return coroutines or we mock them to return results directly if called via asyncio.run)
    # Actually, when using asyncio.run(gitingest_tool(...)), it expects an awaitable.

    async def mock_gitingest_func(*args, **kwargs):
        return {
            "success": True,
            "summary": {
                "total_files_processed": 5,
                "total_size_bytes": 500,
                "file_types": {".py": 5},
                "code_metrics": {"total_functions": 1, "total_classes": 0}
            },
            "tree": "root/\n  main.py",
            "content": {"main.py": "def test(): pass"}
        }

    mock_gitingest.side_effect = mock_gitingest_func

    # Create mock repo
    repo_path = temp_artifact_dir / "my_repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # 2. Run Analyze
    artifacts_path = temp_artifact_dir / "artifacts"
    result_analyze = runner.invoke(app, ["analyze", str(repo_path), "--output-dir", str(artifacts_path)])

    if result_analyze.exit_code != 0:
        print(f"STDOUT: {result_analyze.stdout}")
        if result_analyze.exception:
            print(f"EXCEPTION: {result_analyze.exception}")

    assert result_analyze.exit_code == 0

    # Find the run_id directory
    run_dirs = list(artifacts_path.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "repo.json").exists()

    # 3. Setup Mock Generation
    async def mock_generate_func(*args, **kwargs):
        return {
            "success": True,
            "project_title": "Integrated Project",
            "tech_stack": ["Python", "Pytest"],
            "bullet_points": ["Integrated test point"],
            "future_plans": "Continuous Integration",
            "interview_questions": ["How did you test this?"]
        }

    mock_generate.side_effect = mock_generate_func

    # 4. Run Generate pointing to the artifact directory
    result_generate = runner.invoke(app, ["generate", str(run_dir), "--output-dir", str(artifacts_path)])

    if result_generate.exit_code != 0:
        print(f"STDOUT: {result_generate.stdout}")
        if result_generate.exception:
            print(f"EXCEPTION: {result_generate.exception}")

    assert result_generate.exit_code == 0
    assert "Resume generated successfully!" in result_generate.stdout
    assert (run_dir / "resume" / "resume.json").exists()
    assert (run_dir / "resume" / "resume.md").exists()

    # Verify content of generated markdown
    md_content = (run_dir / "resume" / "resume.md").read_text()
    assert "# Integrated Project" in md_content
    assert "Python, Pytest" in md_content
