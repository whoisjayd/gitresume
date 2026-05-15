from pathlib import Path

import pytest

from gitresume.services.ingestion_service import RepositoryIngestionService


@pytest.mark.asyncio
async def test_ingestion_pipeline_classifies_selects_and_analyzes_ranked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.js").write_text("noise", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')

    monkeypatch.setattr("gitresume.services.ingestion_service.shutil.which", lambda _: None)

    service = RepositoryIngestionService()
    context = await service.build_context(tmp_path)

    assert context["strategy"] == "ranked-files"
    assert context["project_profile"].project_type == "backend-api"
    assert "src/api/main.py" in context["selected_files"]
    assert "node_modules/noise.js" not in context["selected_files"]
    assert context["file_analyses"]


@pytest.mark.asyncio
async def test_build_context_returns_structured_evidence_and_prompt_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')

    monkeypatch.setattr("gitresume.services.ingestion_service.shutil.which", lambda _: None)

    async def fake_analyze_ranked_files(
        self: RepositoryIngestionService, repository_path: Path, selected_paths: list[str]
    ) -> list[dict[str, object]]:
        return [{"success": True, "file_info": {"path": selected_paths[0]}}]

    monkeypatch.setattr(
        RepositoryIngestionService, "analyze_ranked_files", fake_analyze_ranked_files
    )

    context = await RepositoryIngestionService().build_context(tmp_path)

    assert context["inventory"]["total_files"] >= 2
    assert context["inventory"]["selected_file_count"] == len(context["selected_files"])
    assert "python" in context["inventory"]["languages"]
    assert "fastapi" in context["inventory"]["frameworks"]
    assert context["dependency_graph"]["nodes"]
    assert context["dependency_graph"]["edges"]
    assert context["git_history"] == {"recent_commits": [], "high_churn_files": []}
    assert context["token_budget"]["prompt_context_tokens"] > 0
    assert "src/api/main.py" in context["prompt_context"]
    assert '"inventory"' in context["prompt_context"]
