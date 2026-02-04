import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gitresume_core.bulk import parse_input_file, process_bulk


def test_parse_input_file_txt(tmp_path):
    txt_file = tmp_path / "inputs.txt"
    txt_file.write_text("repo1\nrepo2\n  repo3  \n")

    results = parse_input_file(str(txt_file))
    assert results == ["repo1", "repo2", "repo3"]


def test_parse_input_file_json(tmp_path):
    json_file = tmp_path / "inputs.json"
    json_file.write_text(json.dumps(["repo1", "repo2"]))

    results = parse_input_file(str(json_file))
    assert results == ["repo1", "repo2"]


def test_parse_input_file_json_invalid(tmp_path):
    json_file = tmp_path / "invalid.json"
    json_file.write_text(json.dumps({"not": "a list"}))

    with pytest.raises(ValueError, match="JSON input must be a list of paths"):
        parse_input_file(str(json_file))


def test_parse_input_file_csv(tmp_path):
    csv_file = tmp_path / "inputs.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["repo1"])
        writer.writerow(["repo2"])

    results = parse_input_file(str(csv_file))
    assert results == ["repo1", "repo2"]


def test_parse_input_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_input_file("non_existent_file.txt")


@pytest.mark.asyncio
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_analyze(mock_artifact_manager, mock_gitingest, tmp_path):
    # Setup mocks
    mock_gitingest.return_value = {"success": True, "summary": {"file_types": {"py": 10}}, "content": "some content"}

    # Mock ArtifactManager instance
    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance
    mock_manager_instance.run_id = "test-run-id"

    inputs = ["repo1", "repo2"]
    output_dir = str(tmp_path / "artifacts")

    result = await process_bulk(inputs, mode="analyze", output_dir=output_dir)

    assert result["total"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
    assert len(result["details"]) == 2
    assert result["details"][0]["run_id"] == "test-run-id"

    assert mock_gitingest.call_count == 2
    assert mock_artifact_manager.call_count == 2


@pytest.mark.asyncio
@patch("gitresume_core.bulk.clone_repo_tool")
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_with_url(mock_artifact_manager, mock_gitingest, mock_clone, tmp_path):
    # Setup mocks
    mock_clone.return_value = {"success": True, "local_path": "/tmp/local_repo"}
    mock_gitingest.return_value = {"success": True, "summary": {}, "content": ""}

    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance
    mock_manager_instance.run_id = "test-run-id"

    inputs = ["https://github.com/user/repo"]
    output_dir = str(tmp_path / "artifacts")

    result = await process_bulk(inputs, mode="analyze", output_dir=output_dir)

    assert result["success"] == 1
    mock_clone.assert_called_once()
    # Ensure it uses the local path for gitingest
    mock_gitingest.assert_called_with("/tmp/local_repo")


@pytest.mark.asyncio
@patch("gitresume_core.bulk.generate_resume_from_data")
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_generate(mock_artifact_manager, mock_gitingest, mock_generate, tmp_path):
    # Setup mocks
    mock_gitingest.return_value = {"success": True, "summary": {}, "content": ""}
    mock_generate.return_value = {"success": True, "resume": "data"}

    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance
    mock_manager_instance.run_id = "test-run-id"
    mock_manager_instance.base_path = tmp_path / "artifacts" / "test-run-id"

    # Ensure (path_obj / "repo.json").exists() returns False to trigger auto-analyze
    with patch.object(Path, "exists", return_value=False):
        inputs = ["repo1"]
        output_dir = str(tmp_path / "artifacts")

        result = await process_bulk(inputs, mode="generate", output_dir=output_dir)

        assert result["success"] == 1
        assert mock_generate.call_count == 1
        assert mock_gitingest.call_count == 1


@pytest.mark.asyncio
@patch("gitresume_core.bulk.clone_repo_tool")
async def test_process_bulk_clone_failure(mock_clone, tmp_path):
    mock_clone.return_value = {"success": False, "error": "Clone failed"}
    inputs = ["https://github.com/user/repo"]
    output_dir = str(tmp_path / "artifacts")
    result = await process_bulk(inputs, mode="analyze", output_dir=output_dir)
    assert result["success"] == 0
    assert "Failed to clone repository: Clone failed" in result["details"][0]["error"]


@pytest.mark.asyncio
async def test_process_bulk_invalid_mode(tmp_path):
    inputs = ["repo1"]
    output_dir = str(tmp_path / "artifacts")
    result = await process_bulk(inputs, mode="invalid", output_dir=output_dir)
    assert result["success"] == 0
    assert "Invalid mode: invalid" in result["details"][0]["error"]


@pytest.mark.asyncio
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_progress_callback(mock_artifact_manager, mock_gitingest, tmp_path):
    mock_gitingest.return_value = {"success": True, "summary": {}, "content": ""}
    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance

    callback = MagicMock()
    inputs = ["repo1", "repo2"]
    output_dir = str(tmp_path / "artifacts")

    await process_bulk(inputs, mode="analyze", output_dir=output_dir, progress_callback=callback)
    assert callback.call_count == 2
    callback.assert_any_call("repo1", True)
    callback.assert_any_call("repo2", True)


@pytest.mark.asyncio
@patch("gitresume_core.bulk.generate_resume_from_data")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_generate_existing_artifact(mock_artifact_manager, mock_generate, tmp_path):
    # Setup: simulate existing repo.json in a directory
    artifact_dir = tmp_path / "artifacts" / "existing-run"
    artifact_dir.mkdir(parents=True)
    repo_json = artifact_dir / "repo.json"
    repo_json.write_text(json.dumps({"success": True, "data": "existing"}))

    mock_generate.return_value = {"success": True, "resume": "data"}
    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance
    mock_manager_instance.load_artifact.return_value = {"success": True, "data": "existing"}
    mock_manager_instance.base_path = artifact_dir

    inputs = [str(artifact_dir)]
    output_dir = str(tmp_path / "artifacts")

    result = await process_bulk(inputs, mode="generate", output_dir=output_dir)
    assert result["success"] == 1
    mock_manager_instance.load_artifact.assert_called_with("repo.json")
    mock_generate.assert_called()


@pytest.mark.asyncio
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_generate_auto_analyze_failure(mock_artifact_manager, mock_gitingest, tmp_path):
    mock_gitingest.return_value = {"success": False, "error": "Auto-analyze failed"}
    inputs = ["repo1"]
    output_dir = str(tmp_path / "artifacts")
    result = await process_bulk(inputs, mode="generate", output_dir=output_dir)
    assert result["success"] == 0
    assert "Auto-analyze failed" in result["details"][0]["error"]


@pytest.mark.asyncio
@patch("gitresume_core.bulk.generate_resume_from_data")
@patch("gitresume_core.bulk.gitingest_tool")
@patch("gitresume_core.bulk.ArtifactManager")
async def test_process_bulk_generate_resume_failure(mock_artifact_manager, mock_gitingest, mock_generate, tmp_path):
    mock_gitingest.return_value = {"success": True, "summary": {}, "content": ""}
    mock_generate.return_value = {"success": False, "error": "Resume generation failed"}

    mock_manager_instance = MagicMock()
    mock_artifact_manager.return_value = mock_manager_instance

    inputs = ["repo1"]
    output_dir = str(tmp_path / "artifacts")
    result = await process_bulk(inputs, mode="generate", output_dir=output_dir)
    assert result["success"] == 0
    assert "Resume generation failed" in result["details"][0]["error"]
