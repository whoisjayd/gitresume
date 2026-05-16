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
async def test_litellm_client_uses_responses_api_for_responses_mode(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    completion_calls = []
    responses_calls = []

    async def fake_acompletion(**kwargs):
        completion_calls.append(kwargs)
        raise AssertionError("chat completion should not be used for responses-mode models")

    async def fake_aresponses(**kwargs):
        responses_calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "project_title": "Project",
                    "tech_stack": ["Python"],
                    "bullet_points": ["Built API", "Added tests", "Shipped worker"],
                }
            )
        )

    monkeypatch.setattr(litellm_client, "acompletion", fake_acompletion)
    monkeypatch.setattr(litellm_client.litellm, "aresponses", fake_aresponses, raising=False)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    await client.generate_resume(
        [{"role": "user", "content": "hello"}],
        model="chatgpt/codex-mini-latest",
        provider_api_key="oauth-token",
        model_mode="responses",
    )

    assert completion_calls == []
    assert responses_calls[0]["model"] == "chatgpt/codex-mini-latest"
    assert responses_calls[0]["api_key"] == "oauth-token"
    assert responses_calls[0]["input"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_litellm_client_reports_responses_unavailable_when_litellm_api_missing(
    monkeypatch,
) -> None:
    from gitresume.ai import litellm_client

    monkeypatch.delattr(litellm_client.litellm, "aresponses", raising=False)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    with pytest.raises(RuntimeError, match="Responses API execution is not available"):
        await client.generate_resume(
            [{"role": "user", "content": "hello"}],
            model="chatgpt/codex-mini-latest",
            model_mode="responses",
        )


@pytest.mark.asyncio
async def test_litellm_client_parses_dict_responses_output_text(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    async def fake_aresponses(**kwargs):
        del kwargs
        return {
            "output_text": json.dumps(
                {
                    "project_title": "Dict Project",
                    "tech_stack": ["Python"],
                    "bullet_points": ["Built API", "Added tests", "Shipped worker"],
                }
            )
        }

    monkeypatch.setattr(litellm_client.litellm, "aresponses", fake_aresponses, raising=False)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    result = await client.generate_resume(
        [{"role": "user", "content": "hello"}],
        model="chatgpt/codex-mini-latest",
        model_mode="responses",
    )

    assert result.project_title == "Dict Project"


@pytest.mark.asyncio
async def test_litellm_client_parses_dict_responses_output_items(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    async def fake_aresponses(**kwargs):
        del kwargs
        return {
            "output": [
                {
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "project_title": "Nested Dict Project",
                                    "tech_stack": ["Python"],
                                    "bullet_points": [
                                        "Built API",
                                        "Added tests",
                                        "Shipped worker",
                                    ],
                                }
                            )
                        }
                    ]
                }
            ]
        }

    monkeypatch.setattr(litellm_client.litellm, "aresponses", fake_aresponses, raising=False)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    result = await client.generate_resume(
        [{"role": "user", "content": "hello"}],
        model="chatgpt/codex-mini-latest",
        model_mode="responses",
    )

    assert result.project_title == "Nested Dict Project"


@pytest.mark.asyncio
async def test_litellm_client_rejects_malformed_responses_payload(monkeypatch) -> None:
    from gitresume.ai import litellm_client

    async def fake_aresponses(**kwargs):
        del kwargs
        return {"unexpected": "shape"}

    monkeypatch.setattr(litellm_client.litellm, "aresponses", fake_aresponses, raising=False)
    client = litellm_client.LiteLLMResumeClient(Settings(environment="test"))

    with pytest.raises(ValueError, match="empty response"):
        await client.generate_resume(
            [{"role": "user", "content": "hello"}],
            model="chatgpt/codex-mini-latest",
            model_mode="responses",
        )
