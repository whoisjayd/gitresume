import json
from types import SimpleNamespace

import pytest

from gitresume.core.config import Settings


@pytest.mark.asyncio
async def test_litellm_client_uses_model_override_and_provider_api_key(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "project_title": "Project",
                                "tech_stack": ["Python"],
                                "bullet_points": ["Built API", "Added tests", "Shipped worker"],
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(litellm_client, "acompletion", fake_acompletion)

    client = litellm_client.LiteLLMResumeClient(
        Settings(ai_model="gemini/gemini-1.5-flash", environment="test")
    )

    await client.generate_resume(
        [{"role": "user", "content": "hello"}],
        model="openai/gpt-4o-mini",
        provider_api_key="sk-secret",
    )

    assert calls[0]["model"] == "openai/gpt-4o-mini"
    assert calls[0]["api_key"] == "sk-secret"


@pytest.mark.asyncio
async def test_litellm_client_keeps_chat_completion_path_for_responses_mode(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "project_title": "Project",
                                "tech_stack": ["Python"],
                                "bullet_points": ["Built API", "Added tests", "Shipped worker"],
                            }
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(litellm_client, "acompletion", fake_acompletion)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    await client.generate_resume(
        [{"role": "user", "content": "hello"}],
        model="chatgpt/codex-mini-latest",
        model_mode="responses",
    )

    assert calls[0]["model"] == "chatgpt/codex-mini-latest"
    assert "responses" not in calls[0]
