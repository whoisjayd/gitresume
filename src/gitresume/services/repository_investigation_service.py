import json
from pathlib import Path

from pydantic import ValidationError

from gitresume.ai.litellm_client import AIClient
from gitresume.ai.prompts import build_evidence_synthesis_prompt, build_investigation_plan_prompt
from gitresume.schemas.investigation import (
    EvidenceBrief,
    InvestigationAction,
    InvestigationObservation,
)
from gitresume.services.analysis_tools import AnalysisToolError, RepositoryAnalysisTools


class RepositoryInvestigationError(RuntimeError):
    """Raised when guided repository investigation cannot produce a valid brief."""


class RepositoryInvestigationService:
    """Run bounded, read-only LLM-guided repository investigation."""

    allowed_action_types = {"rg", "read", "traverse", "glob"}

    async def investigate(
        self,
        *,
        repo_root: str | Path,
        initial_context: dict[str, object] | str,
        ai_client: AIClient,
        model: str | None = None,
        provider_api_key: str | None = None,
        model_mode: str | None = None,
        max_actions: int = 6,
        max_chars_per_observation: int = 4_000,
        max_observations: int = 6,
        allowed_paths: set[str] | None = None,
        contribution_context: str | None = None,
    ) -> EvidenceBrief:
        if max_actions < 1 or max_observations < 1 or max_chars_per_observation < 1:
            raise RepositoryInvestigationError("Invalid investigation budget.")

        initial_context_text = self._initial_context_text(initial_context)
        if contribution_context:
            initial_context_text = (
                f"{initial_context_text}\n\nContribution scope (trusted git metadata):\n"
                f"{contribution_context}"
            )
        plan_messages = build_investigation_plan_prompt(
            initial_context=initial_context_text,
            max_actions=max_actions,
        )
        try:
            plan_payload = await ai_client.generate_json(
                plan_messages,
                model=model,
                provider_api_key=provider_api_key,
                model_mode=model_mode,
            )
        except Exception as error:
            raise RepositoryInvestigationError("Guided investigation planning failed.") from error

        tools = RepositoryAnalysisTools(repo_root, allowed_paths=allowed_paths)
        observations = self._execute_plan(
            plan_payload,
            tools=tools,
            max_actions=max_actions,
            max_chars_per_observation=max_chars_per_observation,
            max_observations=max_observations,
        )
        observations_json = json.dumps(
            [observation.model_dump(mode="json") for observation in observations],
            indent=2,
            sort_keys=True,
        )
        synthesis_messages = build_evidence_synthesis_prompt(
            initial_context=initial_context_text,
            observations_json=observations_json,
        )
        try:
            brief_payload = await ai_client.generate_json(
                synthesis_messages,
                model=model,
                provider_api_key=provider_api_key,
                model_mode=model_mode,
            )
            return EvidenceBrief.model_validate(brief_payload)
        except Exception as error:
            raise RepositoryInvestigationError("Guided investigation synthesis failed.") from error

    def _execute_plan(
        self,
        plan_payload: dict[str, object],
        *,
        tools: RepositoryAnalysisTools,
        max_actions: int,
        max_chars_per_observation: int,
        max_observations: int,
    ) -> list[InvestigationObservation]:
        raw_actions = plan_payload.get("actions")
        if not isinstance(raw_actions, list):
            raw_actions = []

        observations: list[InvestigationObservation] = []
        for raw_action in raw_actions[:max_actions]:
            if len(observations) >= max_observations:
                break
            observation = self._execute_raw_action(raw_action, tools=tools)
            observations.append(
                self._truncate_observation(
                    observation,
                    max_chars=max_chars_per_observation,
                )
            )
        return observations

    def _execute_raw_action(
        self, raw_action: object, *, tools: RepositoryAnalysisTools
    ) -> InvestigationObservation:
        if not isinstance(raw_action, dict):
            return InvestigationObservation(
                action_type="unknown",
                status="error",
                error="Unsupported investigation action.",
            )
        raw_type = raw_action.get("type")
        action_type = raw_type if isinstance(raw_type, str) else "unknown"
        if action_type not in self.allowed_action_types:
            return InvestigationObservation(
                action_type="unknown",
                status="error",
                error="Unsupported investigation action.",
            )
        try:
            action = InvestigationAction.model_validate(raw_action)
            result = self._execute_action(action, tools=tools)
            return InvestigationObservation(action_type=action.type, status="ok", result=result)
        except (AnalysisToolError, ValidationError, OSError, UnicodeError, ValueError):
            return InvestigationObservation(
                action_type=action_type,
                status="error",
                error="Investigation action could not be completed safely.",
            )

    def _execute_action(
        self, action: InvestigationAction, *, tools: RepositoryAnalysisTools
    ) -> object:
        if action.type == "glob":
            assert action.pattern is not None
            return tools.glob(action.pattern, limit=action.limit)
        if action.type == "traverse":
            return tools.traverse(
                action.path or ".", max_depth=action.max_depth, limit=action.limit
            )
        if action.type == "read":
            assert action.path is not None
            read_result = tools.read(
                action.path,
                start_line=action.start_line,
                end_line=action.end_line,
            )
            return {
                "path": read_result.path,
                "start_line": read_result.start_line,
                "end_line": read_result.end_line,
                "content": read_result.content,
            }
        if action.type == "rg":
            assert action.pattern is not None
            matches = tools.rg(
                action.pattern,
                include_glob=action.include_glob,
                max_matches=action.max_matches,
            )
            return [
                {"path": match.path, "line_number": match.line_number, "line": match.line}
                for match in matches
            ]
        raise AssertionError(f"Unhandled action type: {action.type}")

    def _truncate_observation(
        self, observation: InvestigationObservation, *, max_chars: int
    ) -> InvestigationObservation:
        encoded = json.dumps(observation.model_dump(mode="json"), sort_keys=True)
        if len(encoded) <= max_chars:
            return observation
        truncated_result = encoded[:max_chars] + "... [truncated]"
        return InvestigationObservation(
            action_type=observation.action_type,
            status=observation.status,
            result=truncated_result,
            error=observation.error,
            truncated=True,
        )

    def _initial_context_text(self, initial_context: dict[str, object] | str) -> str:
        if isinstance(initial_context, str):
            return initial_context
        prompt_context = initial_context.get("prompt_context")
        if isinstance(prompt_context, str):
            return prompt_context
        return json.dumps(initial_context, default=str, sort_keys=True)
