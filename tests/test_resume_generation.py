from gitresume.schemas.resume import ResumeDraft
from gitresume.services.resume_generation_service import ResumeGenerationService


class FakeAIClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def generate_resume(self, messages: list[dict[str, str]]) -> ResumeDraft:
        self.messages = messages
        return ResumeDraft(
            project_title="GitResume",
            tech_stack=["FastAPI", "React"],
            bullet_points=[
                "Built a self-hostable resume generator.",
                "Integrated repository analysis for evidence-backed bullets.",
                "Designed an API-first generation workflow.",
            ],
        )


async def test_resume_generation_builds_prompt_and_validates_schema() -> None:
    client = FakeAIClient()
    service = ResumeGenerationService(client)

    result = await service.generate(
        repo_context="Repository uses FastAPI.", job_description="Backend role"
    )

    assert result.project_title == "GitResume"
    assert result.tech_stack == ["FastAPI", "React"]
    assert len(result.bullet_points) == 3
    assert "Backend role" in client.messages[1]["content"]
    assert "Repository uses FastAPI" in client.messages[1]["content"]


async def test_resume_generation_prompt_includes_evidence_guardrails() -> None:
    client = FakeAIClient()
    service = ResumeGenerationService(client)

    await service.generate(repo_context='{"selected_files": ["src/api/main.py"]}')

    combined_prompt = "\n".join(message["content"] for message in client.messages)

    assert "evidence-backed" in combined_prompt
    assert "Do not invent" in combined_prompt
    assert "file/path evidence" in combined_prompt
    assert "architecture" in combined_prompt
    assert "performance" in combined_prompt
    assert "testing" in combined_prompt
    assert "deployment" in combined_prompt
    assert "security" in combined_prompt
