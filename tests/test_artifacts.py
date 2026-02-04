import json

from gitresume_core.artifacts import ArtifactManager


def test_artifact_manager_initialization(temp_artifact_dir):
    manager = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="test_run")
    inputs = {"repo": "test/repo"}
    manager.initialize(inputs)

    assert (temp_artifact_dir / "test_run").exists()
    assert (temp_artifact_dir / "test_run" / "manifest.json").exists()

    with open(temp_artifact_dir / "test_run" / "manifest.json", "r") as f:
        data = json.load(f)
        assert data["run_id"] == "test_run"
        assert data["inputs"] == inputs

def test_save_artifact_json(temp_artifact_dir):
    manager = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="test_run")
    manager.initialize({})

    data = {"key": "value"}
    path = manager.save_artifact("data.json", data, type="json")

    assert path.exists()
    assert path.name == "data.json"

    with open(path, "r") as f:
        assert json.load(f) == data

    # Check manifest update
    with open(temp_artifact_dir / "test_run" / "manifest.json", "r") as f:
        manifest = json.load(f)
        assert len(manifest["outputs"]) == 1
        assert manifest["outputs"][0]["name"] == "data.json"

def test_save_artifact_text(temp_artifact_dir):
    manager = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="test_run")
    manager.initialize({})

    data = "Hello World"
    path = manager.save_artifact("hello.txt", data, type="text")

    assert path.exists()
    assert path.read_text() == data

def test_load_artifact(temp_artifact_dir):
    manager = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="test_run")
    manager.initialize({})

    data = {"hello": "world"}
    manager.save_artifact("test.json", data)

    loaded = manager.load_artifact("test.json")
    assert loaded == data

def test_list_runs(temp_artifact_dir):
    # Create two runs
    manager1 = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="run1")
    manager1.initialize({"id": 1})
    manager1.finalize()

    import time
    time.sleep(0.1) # Ensure different timestamps

    manager2 = ArtifactManager(base_dir=str(temp_artifact_dir), run_id="run2")
    manager2.initialize({"id": 2})
    manager2.finalize()

    runs = ArtifactManager.list_runs(base_dir=str(temp_artifact_dir))
    assert len(runs) == 2
    assert runs[0]["run_id"] == "run2" # Sorted by timestamp descending
    assert runs[1]["run_id"] == "run1"
