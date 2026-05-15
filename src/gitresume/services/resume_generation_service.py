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
    ) -> ResumeDraft:
        messages = build_resume_prompt(repo_context=repo_context, job_description=job_description)
        return await self.ai_client.generate_resume(messages)
