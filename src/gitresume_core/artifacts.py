import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gitresume_core.version import get_tool_version


class ArtifactManager:
    """Manages the lifecycle of run artifacts."""

    def __init__(self, base_dir: str = "artifacts", run_id: str | None = None):
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + str(uuid.uuid4())[:8]
        self.base_path = Path(base_dir) / self.run_id
        self.logs_path = self.base_path / "logs"
        self.manifest_path = self.base_path / "manifest.json"
        self.start_time = time.time()

        self.manifest_data: dict[str, Any] = {
            "schema_version": "1.0",
            "tool_version": get_tool_version(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "inputs": {},
            "outputs": [],
            "stats": {"duration_seconds": 0, "file_counts": {}, "token_usage": {}},
        }

    def initialize(self, inputs: dict[str, Any]):
        """Initializes the artifact directory and manifest."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)
        self.manifest_data["inputs"] = inputs
        self._write_manifest()

    def get_log_file(self) -> Path:
        """Returns the path to the run log file."""
        return self.logs_path / "run.log"

    def save_artifact(self, name: str, data: Any, type: str = "json") -> Path:
        """Saves an artifact file and records it in the manifest."""
        file_path = self.base_path / name

        if type == "json":
            content = json.dumps(data, indent=2)
            file_path.write_text(content)
        elif isinstance(data, str):
            content = data
            file_path.write_text(content)
        else:
            content = data
            file_path.write_bytes(content)

        # Calculate hash
        sha256_hash = hashlib.sha256(content if isinstance(content, bytes) else content.encode()).hexdigest()

        # Update manifest
        self.manifest_data["outputs"].append(
            {
                "name": name,
                "path": str(file_path.relative_to(self.base_path)),
                "sha256": sha256_hash,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_manifest()
        return file_path

    def update_stats(self, stats: dict[str, Any]):
        """Updates the stats in the manifest."""
        self.manifest_data["stats"].update(stats)
        self._write_manifest()

    def load_artifact(self, name: str) -> Any:
        """Loads an artifact file."""
        file_path = self.base_path / name
        if not file_path.exists():
            raise FileNotFoundError(f"Artifact '{name}' not found in {self.base_path}")

        if file_path.suffix == ".json":
            with open(file_path) as f:
                return json.load(f)
        return file_path.read_text()

    def finalize(self):
        """Finalizes the manifest with final stats."""
        self.manifest_data["stats"]["duration_seconds"] = round(time.time() - self.start_time, 2)
        self._write_manifest()

    def _write_manifest(self):
        """Writes the current manifest to disk."""
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f, indent=2)

    @staticmethod
    def list_runs(base_dir: str = "artifacts") -> list[dict[str, Any]]:
        """Lists all runs in the artifacts directory."""
        base_path = Path(base_dir)
        if not base_path.exists():
            return []

        runs = []
        for manifest_file in base_path.glob("*/manifest.json"):
            try:
                with open(manifest_file) as f:
                    data = json.load(f)
                    runs.append(data)
            except (OSError, json.JSONDecodeError):
                continue

        # Sort by timestamp descending
        runs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return runs
