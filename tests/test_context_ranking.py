from pathlib import Path

from gitresume.services.context_ranking import RankedContextBuilder


def test_ranked_context_ignores_generated_vendor_and_secret_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "node_modules" / "library.js").write_text("export default {}", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("lock", encoding="utf-8")

    ranked = RankedContextBuilder(tmp_path).rank_files(limit=10)

    assert [item.path for item in ranked] == ["src/main.py"]


def test_ranked_context_prioritizes_resume_relevant_entrypoints(tmp_path: Path) -> None:
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "api" / "routes.py").write_text(
        "async def websocket_handler():\n    return 'FastAPI Redis OAuth API'\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "notes.md").write_text("misc notes", encoding="utf-8")

    ranked = RankedContextBuilder(tmp_path).rank_files(limit=5)

    assert ranked[0].path == "src/api/routes.py"
    assert "source code" in ranked[0].reasons
    assert "resume-relevant implementation terms" in ranked[0].reasons


def test_ranked_context_contains_only_selected_high_ranked_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("class Service:\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")

    context = RankedContextBuilder(tmp_path).build_ranked_context(file_limit=1)

    assert "## src/service.py" in context
    assert "## README.md" not in context


def test_ranked_context_scores_major_language_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "handler.go").write_text(
        'package src\nfunc Handler() string { return "grpc api service" }\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "Controller.java").write_text(
        "class Controller { void route() { /* spring api */ } }\n",
        encoding="utf-8",
    )

    ranked_paths = [item.path for item in RankedContextBuilder(tmp_path).rank_files(limit=5)]

    assert "src/handler.go" in ranked_paths
    assert "src/Controller.java" in ranked_paths
