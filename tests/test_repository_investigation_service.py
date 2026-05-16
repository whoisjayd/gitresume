from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from gitresume.schemas.investigation import EvidenceBrief, InvestigationAction
from gitresume.services.repository_investigation_service import RepositoryInvestigationService


class FakeInvestigationAIClient:
    def __init__(self, payloads: list[dict[str, Any] | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, Any]] = []

    async def generate_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "provider_api_key": provider_api_key,
                "model_mode": model_mode,
            }
        )
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def write_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# Demo\nFastAPI service with health checks.\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_investigation_executes_planned_tools_and_returns_evidence_brief(
    tmp_path: Path,
) -> None:
    repo_root = write_repo(tmp_path)
    ai_client = FakeInvestigationAIClient(
        [
            {
                "actions": [
                    {"type": "glob", "pattern": "**/*.py", "limit": 10},
                    {"type": "read", "path": "src/app.py", "start_line": 1, "end_line": 5},
                    {"type": "rg", "pattern": "FastAPI", "include_glob": "*.md", "max_matches": 5},
                ]
            },
            {
                "summary": "FastAPI service with a health endpoint.",
                "claims": [
                    {
                        "claim": "Implements a FastAPI health endpoint.",
                        "evidence": [
                            {
                                "path": "src/app.py",
                                "start_line": 1,
                                "end_line": 5,
                                "quote": "app = FastAPI()",
                            }
                        ],
                    }
                ],
                "notable_files": ["src/app.py"],
            },
        ]
    )
    service = RepositoryInvestigationService()

    brief = await service.investigate(
        repo_root=repo_root,
        initial_context={"prompt_context": "initial compact context"},
        ai_client=ai_client,
        model="openai/gpt-4o-mini",
        provider_api_key="sk-test",
        model_mode="chat",
        max_actions=5,
        max_chars_per_observation=500,
        max_observations=5,
    )

    assert brief.claims[0].claim == "Implements a FastAPI health endpoint."
    assert brief.claims[0].evidence[0].path == "src/app.py"
    assert len(ai_client.calls) == 2
    synthesis_prompt = ai_client.calls[1]["messages"][1]["content"]
    assert "glob" in synthesis_prompt
    assert "src/app.py" in synthesis_prompt
    assert "FastAPI" in synthesis_prompt
    assert ai_client.calls[0]["model"] == "openai/gpt-4o-mini"
    assert ai_client.calls[0]["provider_api_key"] == "sk-test"


@pytest.mark.asyncio
async def test_investigation_enforces_action_and_observation_budgets(tmp_path: Path) -> None:
    repo_root = write_repo(tmp_path)
    ai_client = FakeInvestigationAIClient(
        [
            {
                "actions": [
                    {"type": "read", "path": "README.md"},
                    {"type": "read", "path": "src/app.py"},
                    {"type": "glob", "pattern": "**/*"},
                ]
            },
            {"summary": "Budgeted brief.", "claims": [], "notable_files": []},
        ]
    )

    await RepositoryInvestigationService().investigate(
        repo_root=repo_root,
        initial_context={"prompt_context": "initial"},
        ai_client=ai_client,
        max_actions=2,
        max_chars_per_observation=25,
        max_observations=1,
    )

    synthesis_prompt = ai_client.calls[1]["messages"][1]["content"]
    assert synthesis_prompt.count('"action_type"') == 1
    assert "truncated" in synthesis_prompt
    assert "src/app.py" not in synthesis_prompt


@pytest.mark.asyncio
async def test_investigation_records_unknown_action_as_safe_observation_error(
    tmp_path: Path,
) -> None:
    repo_root = write_repo(tmp_path)
    ai_client = FakeInvestigationAIClient(
        [
            {"actions": [{"type": "shell", "command": "cat /etc/passwd"}]},
            {"summary": "No unsafe tools executed.", "claims": [], "notable_files": []},
        ]
    )

    await RepositoryInvestigationService().investigate(
        repo_root=repo_root,
        initial_context={"prompt_context": "initial"},
        ai_client=ai_client,
        max_actions=3,
        max_chars_per_observation=200,
        max_observations=3,
    )

    synthesis_prompt = ai_client.calls[1]["messages"][1]["content"]
    assert "Unsupported investigation action" in synthesis_prompt
    assert "cat /etc/passwd" not in synthesis_prompt


@pytest.mark.asyncio
async def test_investigation_restricts_tools_to_contributed_file_allowlist(
    tmp_path: Path,
) -> None:
    repo_root = write_repo(tmp_path)
    ai_client = FakeInvestigationAIClient(
        [
            {
                "actions": [
                    {"type": "read", "path": "README.md"},
                    {"type": "read", "path": "src/app.py", "start_line": 1, "end_line": 2},
                    {"type": "glob", "pattern": "**/*"},
                ]
            },
            {"summary": "Scoped brief.", "claims": [], "notable_files": ["src/app.py"]},
        ]
    )

    await RepositoryInvestigationService().investigate(
        repo_root=repo_root,
        initial_context={"prompt_context": "initial"},
        ai_client=ai_client,
        allowed_paths={"src/app.py"},
        contribution_context="Author scope: Jaydeep touched src/app.py",
        max_actions=3,
        max_chars_per_observation=1_000,
        max_observations=3,
    )

    planning_prompt = ai_client.calls[0]["messages"][1]["content"]
    synthesis_prompt = ai_client.calls[1]["messages"][1]["content"]
    assert "Author scope: Jaydeep touched src/app.py" in planning_prompt
    assert "Investigation action could not be completed safely" in synthesis_prompt
    assert '"path": "src/app.py"' in synthesis_prompt
    assert '"README.md"' not in synthesis_prompt


def test_investigation_action_schema_rejects_unknown_and_unsafe_values() -> None:
    with pytest.raises(ValidationError):
        InvestigationAction.model_validate({"type": "shell", "command": "ls"})

    with pytest.raises(ValidationError):
        InvestigationAction.model_validate({"type": "read", "path": "../secret.txt"})

    with pytest.raises(ValidationError):
        InvestigationAction.model_validate({"type": "rg", "pattern": "x", "max_matches": 0})

    with pytest.raises(ValidationError):
        InvestigationAction.model_validate({"type": "rg", "pattern": "x" * 513})


def test_evidence_brief_formats_compact_context_with_paths_and_lines() -> None:
    brief = EvidenceBrief.model_validate(
        {
            "summary": "FastAPI service.",
            "claims": [
                {
                    "claim": "Has a health endpoint.",
                    "evidence": [
                        {
                            "path": "src/app.py",
                            "start_line": 3,
                            "end_line": 5,
                            "quote": "@app.get('/health')",
                        }
                    ],
                }
            ],
            "notable_files": ["src/app.py"],
        }
    )

    compact = brief.to_prompt_context()

    assert "FastAPI service." in compact
    assert "Has a health endpoint." in compact
    assert "src/app.py:3-5" in compact
    assert "@app.get('/health')" in compact


def test_evidence_brief_rejects_claims_without_evidence() -> None:
    with pytest.raises(ValidationError):
        EvidenceBrief.model_validate(
            {
                "summary": "Unsupported brief.",
                "claims": [{"claim": "Has unsupported impact.", "evidence": []}],
                "notable_files": [],
            }
        )
