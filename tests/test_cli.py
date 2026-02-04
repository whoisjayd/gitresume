from typer.testing import CliRunner
from gitresume_cli.main import app
from unittest.mock import patch, AsyncMock
import json
from pathlib import Path

runner = CliRunner()

def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "GitResume version:" in result.stdout

def test_doctor_command():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "GitResume Health Check" in result.stdout
    assert "Python Version" in result.stdout

@patch("gitresume_core.gitingest.gitingest_tool", new_callable=AsyncMock)
def test_analyze_command(mock_gitingest, temp_artifact_dir):
    # Setup mock return value
    mock_gitingest.return_value = {
        "success": True,
        "summary": {
            "total_files_processed": 10,
            "total_size_bytes": 1024,
            "file_types": {".py": 5},
            "code_metrics": {"total_functions": 2, "total_classes": 1}
        },
        "tree": "root/\n  main.py",
        "content": {"main.py": "print('hello')"}
    }

    # Create a dummy git repo for the check in analyze (though we mock the tool)
    repo_path = temp_artifact_dir / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    result = runner.invoke(app, ["analyze", str(repo_path), "--output-dir", str(temp_artifact_dir / "artifacts")])

    if result.exit_code != 0:
        print(f"STDOUT: {result.stdout}")
        if result.exception:
            print(f"EXCEPTION: {result.exception}")

    assert result.exit_code == 0
    assert "Analysis Summary" in result.stdout
    assert "Total Files Processed" in result.stdout

    # Check if artifact was saved
    artifact_dirs = list((temp_artifact_dir / "artifacts").iterdir())
    assert len(artifact_dirs) == 1
    assert (artifact_dirs[0] / "repo.json").exists()

@patch("uvicorn.run")
def test_web_command(mock_uvicorn):
    # Mock webbrowser.open to avoid opening browser during tests
    with patch("webbrowser.open"):
        result = runner.invoke(app, ["web", "--no-open"])
        assert result.exit_code == 0
        assert "Starting GitResume Dashboard" in result.stdout
        mock_uvicorn.assert_called_once()

@patch("gitresume_core.gitingest.gitingest_tool", new_callable=AsyncMock)
def test_analyze_command_fail(mock_gitingest, temp_artifact_dir):
    mock_gitingest.return_value = {"success": False, "error": "Analysis failed"}

    repo_path = temp_artifact_dir / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    result = runner.invoke(app, ["analyze", str(repo_path), "--output-dir", str(temp_artifact_dir)])
    assert result.exit_code == 1
    assert "Analysis failed" in result.stdout

@patch("gitresume_core.create_resume.generate_resume_from_data", new_callable=AsyncMock)
def test_generate_command_from_existing_artifact(mock_generate, temp_artifact_dir):
    # Setup mock artifact
    run_id = "test_run"
    run_dir = temp_artifact_dir / run_id
    run_dir.mkdir()
    repo_json = run_dir / "repo.json"
    repo_json.write_text(json.dumps({
        "success": True,
        "summary": {},
        "tree": "",
        "content": {}
    }))

    # Mock manifest
    manifest_json = run_dir / "manifest.json"
    manifest_json.write_text(json.dumps({
        "run_id": run_id,
        "timestamp": "2026-02-04T12:00:00Z",
        "inputs": {},
        "outputs": [{"name": "repo.json", "path": "repo.json"}],
        "stats": {}
    }))

    # Setup mock return value
    mock_generate.return_value = {
        "success": True,
        "project_title": "Test Project",
        "tech_stack": ["Python"],
        "bullet_points": ["Did things"],
        "future_plans": "More things",
        "interview_questions": ["What?"]
    }

    result = runner.invoke(app, ["generate", str(run_dir), "--output-dir", str(temp_artifact_dir)])

    assert result.exit_code == 0
    assert "Resume generated successfully!" in result.stdout
    assert (run_dir / "resume" / "resume.json").exists()
    assert (run_dir / "resume" / "resume.md").exists()
