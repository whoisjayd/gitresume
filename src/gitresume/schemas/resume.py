from pydantic import BaseModel, Field


class InterviewQuestion(BaseModel):
    question: str
    answer: str
    category: str


class ResumeDraft(BaseModel):
    project_title: str = Field(serialization_alias="projectTitle")
    tech_stack: list[str] = Field(serialization_alias="techStack")
    bullet_points: list[str] = Field(serialization_alias="bulletPoints", min_length=3)
    additional_notes: str = Field(default="", serialization_alias="additionalNotes")
    future_plans: str = Field(default="", serialization_alias="futurePlans")
    potential_advancements: str = Field(default="", serialization_alias="potentialAdvancements")
    interview_questions: list[InterviewQuestion] = Field(
        default_factory=list, serialization_alias="interviewQuestions"
    )
