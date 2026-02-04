import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from gitresume_core.artifacts import ArtifactManager
from gitresume_core.create_resume import generate_resume_from_data, resume_to_markdown
from gitresume_core.git_operations import clone_repo_tool
from gitresume_core.gitingest import gitingest_tool

logger = logging.getLogger(__name__)


def is_url(path: str) -> bool:
    """Checks if a string is a URL."""
    return path.startswith(("http://", "https://", "git@"))


async def _run_analyze_mode(actual_path: str, output_dir: str) -> str:
    """Helper to run analysis mode."""
    manager = ArtifactManager(base_dir=output_dir)
    manager.initialize(inputs={"path": str(Path(actual_path).resolve())})

    ingest_result = await gitingest_tool(actual_path)
    if not ingest_result.get("success"):
        raise ValueError(ingest_result.get("error", "Unknown ingestion error"))

    manager.save_artifact("repo.json", ingest_result)
    summary = ingest_result.get("summary", {})
    manager.update_stats({"file_counts": summary.get("file_types", {})})
    manager.finalize()

    return manager.run_id


async def _run_generate_mode(
    actual_path: str,
    output_dir: str,
    model: str | None = None,
    job_description: str | None = None,
) -> str:
    """Helper to run generation mode."""
    path_obj = Path(actual_path)
    manager = None
    repo_data = None

    # Try to find repo.json if actual_path is an artifact dir
    if (path_obj / "repo.json").exists():
        manager = ArtifactManager(base_dir=str(path_obj.parent), run_id=path_obj.name)
        repo_data = manager.load_artifact("repo.json")
    else:
        # Auto-analyze if repo.json not found
        manager = ArtifactManager(base_dir=output_dir)
        manager.initialize(inputs={"path": str(Path(actual_path).resolve())})

        ingest_result = await gitingest_tool(actual_path)
        if not ingest_result.get("success"):
            raise ValueError(ingest_result.get("error", "Unknown ingestion error"))

        manager.save_artifact("repo.json", ingest_result)
        repo_data = ingest_result

    # 2. Generate Resume
    resume_result = await generate_resume_from_data(
        repo_data=repo_data,
        job_description=job_description,
        model=model,
    )

    if not resume_result.get("success"):
        raise ValueError(resume_result.get("error", "Unknown generation error"))

    # 3. Save Outputs
    resume_dir = manager.base_path / "resume"
    resume_dir.mkdir(parents=True, exist_ok=True)
    manager.save_artifact("resume/resume.json", resume_result)
    md_content = resume_to_markdown(resume_result)
    manager.save_artifact("resume/resume.md", md_content, type="text")
    manager.finalize()

    return manager.run_id


async def _process_single_repo(
    input_path: str,
    mode: str,
    output_dir: str,
    repos_dir: Path,
    semaphore: asyncio.Semaphore,
    model: str | None = None,
    job_description: str | None = None,
) -> dict[str, Any]:
    """Process a single repository (helper for bulk processing)."""
    async with semaphore:
        result: dict[str, Any] = {"input": input_path, "success": False, "error": None, "run_id": None}
        actual_path = input_path
        try:
            # 1. Handle URLs by cloning
            if is_url(input_path):
                clone_result = await clone_repo_tool(input_path, str(repos_dir))
                if not clone_result.get("success"):
                    raise ValueError(f"Failed to clone repository: {clone_result.get('error')}")
                actual_path = clone_result["local_path"]

            if mode == "analyze":
                result["run_id"] = await _run_analyze_mode(actual_path, output_dir)
                result["success"] = True
            elif mode == "generate":
                result["run_id"] = await _run_generate_mode(actual_path, output_dir, model, job_description)
                result["success"] = True
            else:
                raise ValueError(f"Invalid mode: {mode}")

        except Exception as e:
            logger.error(f"Error processing {input_path}: {e}")
            result["error"] = str(e)

        return result


async def process_bulk(
    inputs: list[str],
    mode: str = "analyze",
    concurrency: int = 5,
    output_dir: str = "artifacts",
    model: str | None = None,
    job_description: str | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """
    Process multiple repositories in bulk.

    Args:
        inputs: List of repository paths or URLs.
        mode: 'analyze' or 'generate'.
        concurrency: Number of parallel tasks.
        output_dir: Directory to save artifacts.
        model: LLM model to use (for generate mode).
        job_description: Job description (for generate mode).
        progress_callback: Optional callback for progress updates.

    Returns:
        Summary report.
    """
    semaphore = asyncio.Semaphore(concurrency)

    # Directory to store cloned repositories
    repos_dir = Path(output_dir) / "cloned_repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    async def worker_wrapper(input_path: str) -> dict[str, Any]:
        res = await _process_single_repo(
            input_path=input_path,
            mode=mode,
            output_dir=output_dir,
            repos_dir=repos_dir,
            semaphore=semaphore,
            model=model,
            job_description=job_description,
        )
        if progress_callback:
            progress_callback(input_path, res["success"])
        return res

    tasks = [worker_wrapper(path) for path in inputs]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    return {
        "total": len(inputs),
        "success": success_count,
        "failed": fail_count,
        "details": results,
    }


def parse_input_file(file_path: str) -> list[str]:
    """Parses input file (txt, json, or csv)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    if path.suffix == ".json":
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, list):
                return [str(item) for item in data]
            raise ValueError("JSON input must be a list of paths")
    elif path.suffix == ".csv":
        import csv

        with open(path) as f:
            reader = csv.reader(f)
            return [row[0] for row in reader if row]
    else:
        # Default to plain text (one path per line)
        with open(path) as f:
            return [line.strip() for line in f if line.strip()]
