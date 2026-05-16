from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class InvestigationAction(BaseModel):
    """A bounded, read-only repository investigation action proposed by an LLM."""

    type: Literal["rg", "read", "traverse", "glob"]
    pattern: str | None = Field(default=None, max_length=512)
    path: str | None = None
    include_glob: str | None = None
    start_line: int = Field(default=1, ge=1, le=100_000)
    end_line: int | None = Field(default=None, ge=1, le=100_000)
    max_depth: int = Field(default=2, ge=0, le=5)
    limit: int = Field(default=200, ge=1, le=1_000)
    max_matches: int = Field(default=50, ge=1, le=500)

    @field_validator("path", "pattern", "include_glob")
    @classmethod
    def reject_unsafe_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped or "\x00" in stripped:
            raise ValueError("value must be non-empty and must not contain NUL bytes")
        if stripped.startswith(("/", "\\")) or ".." in stripped.replace("\\", "/").split("/"):
            raise ValueError("value must stay inside the repository")
        return stripped

    @model_validator(mode="after")
    def validate_action_fields(self) -> "InvestigationAction":
        if self.type in {"rg", "glob"} and self.pattern is None:
            raise ValueError(f"{self.type} actions require pattern")
        if self.type == "read" and self.path is None:
            raise ValueError("read actions require path")
        if self.type == "read" and self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class InvestigationObservation(BaseModel):
    """Result of a safe investigation action."""

    action_type: str
    status: Literal["ok", "error"]
    result: Any | None = None
    error: str | None = None
    truncated: bool = False


class EvidenceReference(BaseModel):
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    quote: str = Field(default="", max_length=2_000)

    @field_validator("path")
    @classmethod
    def reject_unsafe_path(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or stripped.startswith(("/", "\\")):
            raise ValueError("path must be relative")
        if ".." in stripped.replace("\\", "/").split("/"):
            raise ValueError("path must stay inside the repository")
        return stripped

    def citation(self) -> str:
        if self.start_line is None:
            return self.path
        if self.end_line is None or self.end_line == self.start_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"


class EvidenceClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=1_000)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=10)


class EvidenceBrief(BaseModel):
    summary: str = Field(default="", max_length=4_000)
    claims: list[EvidenceClaim] = Field(default_factory=list, max_length=20)
    notable_files: list[str] = Field(default_factory=list, max_length=50)

    def to_prompt_context(self) -> str:
        lines = ["Guided repository evidence brief:", "", f"Summary: {self.summary}".strip()]
        if self.claims:
            lines.extend(["", "Evidence-backed claims:"])
            for index, claim in enumerate(self.claims, start=1):
                lines.append(f"{index}. {claim.claim}")
                for evidence in claim.evidence:
                    quote = f" — {evidence.quote}" if evidence.quote else ""
                    lines.append(f"   - {evidence.citation()}{quote}")
        if self.notable_files:
            lines.extend(["", "Notable files:", *[f"- {path}" for path in self.notable_files]])
        return "\n".join(lines).strip()
