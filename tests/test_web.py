import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from gitresume_web.main import app

client = TestClient(app)


def test_list_runs_empty(temp_artifact_dir):
    with patch("gitresume_web.main.ARTIFACTS_DIR", str(temp_artifact_dir)):
        response = client.get("/")
        assert response.status_code == 200
        assert "No runs found" in response.text


def test_list_runs_with_data(temp_artifact_dir):
    # Create a mock run
    run_id = "test_run_web"
    run_dir = temp_artifact_dir / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "timestamp": "2026-02-04T12:00:00Z",
        "inputs": {"path": "/mock/path"},
        "outputs": [],
        "stats": {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    with patch("gitresume_web.main.ARTIFACTS_DIR", str(temp_artifact_dir)):
        response = client.get("/")
        assert response.status_code == 200
        assert run_id in response.text


def test_run_details_not_found(temp_artifact_dir):
    with patch("gitresume_web.main.ARTIFACTS_DIR", str(temp_artifact_dir)):
        response = client.get("/runs/nonexistent")
        assert response.status_code == 404


def test_run_details_success(temp_artifact_dir):
    run_id = "test_run_details"
    run_dir = temp_artifact_dir / run_id
    run_dir.mkdir()
    manifest = {"run_id": run_id, "timestamp": "2026-02-04T12:00:00Z", "inputs": {}, "outputs": [], "stats": {}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "repo.json").write_text(
        json.dumps(
            {
                "summary": {
                    "total_files_processed": 10,
                    "total_size_bytes": 1024,
                    "file_types": {".py": 10},
                    "code_metrics": {"total_functions": 5, "total_classes": 1, "languages": {}},
                }
            }
        )
    )

    resume_dir = run_dir / "resume"
    resume_dir.mkdir()
    (resume_dir / "resume.md").write_text("# My Resume")

    with patch("gitresume_web.main.ARTIFACTS_DIR", str(temp_artifact_dir)):
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        assert run_id in response.text
        assert "My Resume" in response.text


def test_view_resume_success(temp_artifact_dir):
    run_id = "test_view_resume"
    run_dir = temp_artifact_dir / run_id
    run_dir.mkdir()
    resume_dir = run_dir / "resume"
    resume_dir.mkdir()
    (resume_dir / "resume.md").write_text("# Resume Content")

    with patch("gitresume_web.main.ARTIFACTS_DIR", str(temp_artifact_dir)):
        response = client.get(f"/runs/{run_id}/resume")
        assert response.status_code == 200
        assert "Resume Content" in response.text
