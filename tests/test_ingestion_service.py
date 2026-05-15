from pathlib import Path
from typing import Any, cast

import pytest

from gitresume.services.ingestion_service import RepositoryIngestionService


def test_repomix_is_primary_context_strategy_when_npx_exists(monkeypatch) -> None:
    service = RepositoryIngestionService()

    monkeypatch.setattr("gitresume.services.ingestion_service.shutil.which", lambda _: "npx")

    command = service._repomix_command(
        Path("repomix-output.json"), selected_paths=["src/main.py", "README.md"]
    )

    assert command[:4] == ["npx", "--yes", "repomix@1.14.0", "."]
    assert "--compress" in command
    assert "--style" in command
    assert "json" in command
    assert command[-2:] == ["--include", "src/main.py,README.md"]


def test_repomix_command_includes_expanded_selected_context_options() -> None:
    service = RepositoryIngestionService()

    command = service._repomix_command(
        Path("repomix-output.json"), selected_paths=["src/main.py", "README.md"]
    )

    assert "--parsable-style" in command
    assert "--truncate-base64" in command
    assert "--output-show-line-numbers" in command
    assert "--include-full-directory-structure" in command


def test_repomix_command_supports_metadata_only_mode() -> None:
    service = RepositoryIngestionService()

    command = service._repomix_command(Path("repomix-metadata.json"), mode="metadata")

    assert "--no-files" in command
    assert "--token-count-tree" in command
    assert "--top-files-len" in command


def test_repomix_command_supports_git_log_mode() -> None:
    service = RepositoryIngestionService()

    command = service._repomix_command(Path("repomix-logs.json"), mode="git-log")

    assert "--include-logs" in command
    assert command[command.index("--include-logs-count") + 1] == "50"


@pytest.mark.asyncio
async def test_gitingest_digest_forwards_include_and_exclude_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_ingest_async(path: str, **kwargs: object) -> tuple[str, str, str]:
        captured["path"] = path
        captured["kwargs"] = kwargs
        return "summary", "tree", "content"

    monkeypatch.setattr("gitresume.services.ingestion_service.ingest_async", fake_ingest_async)

    digest = await RepositoryIngestionService().digest_with_gitingest(
        tmp_path, selected_paths=["src/main.py", "README.md"]
    )

    assert digest.summary == "summary"
    assert captured["path"] == str(tmp_path)
    kwargs = cast(dict[str, Any], captured["kwargs"])
    assert kwargs["include_patterns"] == {"src/main.py", "README.md"}
    assert "node_modules/*" in kwargs["exclude_patterns"]
    assert "*.min.js" in kwargs["exclude_patterns"]
