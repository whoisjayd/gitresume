import json
from typing import Protocol

import litellm
from litellm import acompletion

from gitresume.core.config import Settings
from gitresume.schemas.resume import ResumeDraft


class AIClient(Protocol):
    async def generate_resume(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
    ) -> ResumeDraft: ...


class LiteLLMResumeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate_resume(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
    ) -> ResumeDraft:
        if model_mode == "responses":
            content = await self._generate_with_responses_api(
                messages,
                model=model or self.settings.ai_model,
                provider_api_key=provider_api_key,
            )
        else:
            kwargs = {
                "model": model or self.settings.ai_model,
                "messages": messages,
                "temperature": self.settings.ai_temperature,
                "timeout": self.settings.ai_timeout_seconds,
                "response_format": {"type": "json_object"},
            }
            if provider_api_key is not None:
                kwargs["api_key"] = provider_api_key
            response = await acompletion(
                **kwargs,
            )
            content = response.choices[0].message.content
        if not content:
            raise ValueError("AI provider returned an empty response.")
        return ResumeDraft.model_validate(json.loads(content))

    async def _generate_with_responses_api(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        provider_api_key: str | None = None,
    ) -> str | None:
        aresponses = getattr(litellm, "aresponses", None)
        if aresponses is None:
            raise RuntimeError("Responses API execution is not available in this LiteLLM version.")
        kwargs = {
            "model": model,
            "input": messages,
            "temperature": self.settings.ai_temperature,
            "timeout": self.settings.ai_timeout_seconds,
            "text": {"format": {"type": "json_object"}},
        }
        if provider_api_key is not None:
            kwargs["api_key"] = provider_api_key
        response = await aresponses(**kwargs)
        content = _response_value(response, "output_text")
        if content:
            return str(content)
        choices = _response_value(response, "choices")
        if choices:
            return choices[0].message.content
        output = _response_value(response, "output")
        if output:
            return _content_from_responses_output(output)
        return None


def _response_value(response: object, key: str) -> object | None:
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


def _content_from_responses_output(output: object) -> str | None:
    if not isinstance(output, list):
        return None
    for item in output:
        content_items = getattr(item, "content", None)
        if content_items is None and isinstance(item, dict):
            content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content_item in content_items:
            text = getattr(content_item, "text", None)
            if text is None and isinstance(content_item, dict):
                text = content_item.get("text")
            if text:
                return str(text)
    return None
