import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from gitresume_core.artifacts import ArtifactManager

app = FastAPI(title="GitResume Dashboard")

# Setup templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Artifacts directory
ARTIFACTS_DIR = os.getenv("GITRESUME_ARTIFACTS_DIR", "artifacts")

@app.get("/", response_class=HTMLResponse)
async def list_runs(request: Request):
    runs = ArtifactManager.list_runs(base_dir=ARTIFACTS_DIR)
    return templates.TemplateResponse("index.html", {"request": request, "runs": runs})

@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_details(request: Request, run_id: str):
    base_path = Path(ARTIFACTS_DIR) / run_id
    manifest_path = base_path / "manifest.json"

    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    # Try to load repo info if it exists
    repo_info = None
    repo_json_path = base_path / "repo.json"
    if repo_json_path.exists():
        with open(repo_json_path, "r") as f:
            repo_info = json.load(f)

    # Try to load resume if it exists
    resume_md = None
    resume_md_path = base_path / "resume" / "resume.md"
    if resume_md_path.exists():
        resume_md = resume_md_path.read_text()

    return templates.TemplateResponse("run_details.html", {
        "request": request,
        "run_id": run_id,
        "manifest": manifest,
        "repo_info": repo_info,
        "resume_md": resume_md
    })

@app.get("/runs/{run_id}/resume", response_class=HTMLResponse)
async def view_resume(request: Request, run_id: str):
    base_path = Path(ARTIFACTS_DIR) / run_id
    resume_md_path = base_path / "resume" / "resume.md"

    if not resume_md_path.exists():
        raise HTTPException(status_code=404, detail="Resume not found")

    resume_md = resume_md_path.read_text()

    return templates.TemplateResponse("resume_view.html", {
        "request": request,
        "run_id": run_id,
        "resume_md": resume_md
    })
