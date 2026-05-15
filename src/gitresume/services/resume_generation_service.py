from gitresume.ai.litellm_client import AIClient
from gitresume.ai.prompts import build_resume_prompt
from gitresume.schemas.resume import ResumeDraft


class ResumeGenerationService:
    def __init__(self, ai_client: AIClient) -> None:
        self.ai_client = ai_client

    async def generate(
        self,
        *,
        repo_context: str,
        job_description: str | None = None,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
    ) -> ResumeDraft:
        messages = build_resume_prompt(repo_context=repo_context, job_description=job_description)
        if model is None and provider_api_key is None and model_mode is None:
            return await self.ai_client.generate_resume(messages)
        return await self.ai_client.generate_resume(
            messages,
            model=model,
            provider_api_key=provider_api_key,
            model_mode=model_mode,
        )
