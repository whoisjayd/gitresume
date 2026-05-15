import json
from typing import Protocol

from litellm import acompletion

from gitresume.core.config import Settings
from gitresume.schemas.resume import ResumeDraft


class AIClient(Protocol):
    async def generate_resume(self, messages: list[dict[str, str]]) -> ResumeDraft: ...


class LiteLLMResumeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate_resume(self, messages: list[dict[str, str]]) -> ResumeDraft:
        response = await acompletion(
            model=self.settings.ai_model,
            messages=messages,
            temperature=self.settings.ai_temperature,
            timeout=self.settings.ai_timeout_seconds,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("AI provider returned an empty response.")
        return ResumeDraft.model_validate(json.loads(content))
