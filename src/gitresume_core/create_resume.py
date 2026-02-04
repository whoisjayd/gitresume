"""
Core tool for generating a resume section from repository analysis.

This module orchestrates the process of taking repository data,
generating a detailed resume section using an AI model, and then
refining the output with grammar correction.
"""

import logging
import os
import re
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from .grammar_check import correct_resume_grammar
from .llm import llm_client
from .prompts import RESUME_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# --- Configuration and Constants ---

# --- AI Model Initialization ---
# Only use the primary AI provider, no fallbacks
PRIMARY_MODEL = os.getenv("AI_MODEL", "gemini/gemini-2.0-flash-lite")


async def _emit_ws_message(websocket: WebSocket | None, msg_type: str, content: Any, generation_id: str):
    """Safely sends a message over a WebSocket connection."""
    if not websocket or websocket.client_state != WebSocketState.CONNECTED:
        return
    try:
        message = {"type": msg_type, "content": content, "generation_id": generation_id}
        await websocket.send_json(message)
    except Exception as e:
        logger.warning(f"WebSocket send error: {e}")


def _build_prompt(
    gitingest_summary: str,
    gitingest_tree: str,
    gitingest_content: str,
    job_description: str | None,
) -> str:
    """Constructs the final prompt for the AI model."""
    job_desc_text = (
        f"The user is applying for a job with this description: {job_description.strip()}" if job_description else "N/A"
    )
    return RESUME_PROMPT_TEMPLATE.format(
        job_description=job_desc_text,
        gitingest_summary=gitingest_summary,
        gitingest_tree=gitingest_tree,
        gitingest_content=gitingest_content,
    )


def resume_to_markdown(data: dict[str, Any]) -> str:
    """Converts resume data dictionary to a Markdown string."""
    md = f"# {data.get('project_title', 'Project')}\n\n"

    if data.get("tech_stack"):
        md += "## Tech Stack\n"
        md += ", ".join(data["tech_stack"]) + "\n\n"

    if data.get("bullet_points"):
        md += "## Key Contributions\n"
        for bp in data["bullet_points"]:
            md += f"- {bp}\n"
        md += "\n"

    if data.get("future_plans"):
        md += "## Future Plans\n"
        md += f"{data['future_plans']}\n\n"

    if data.get("interview_questions"):
        md += "## Interview Preparation\n"
        for q in data["interview_questions"]:
            md += f"- {q}\n"
        md += "\n"

    return md


async def _generate_and_parse_response(prompt: str, model: str | None = None) -> dict[str, Any]:
    """Calls the AI model and parses the JSON response."""
    try:
        messages = [{"role": "user", "content": prompt}]
        return await llm_client.generate_json_completion(
            messages=messages, model=model or PRIMARY_MODEL, temperature=0.1
        )
    except Exception as e:
        logger.error(f"Failed to generate or parse AI response: {e}")
        raise ValueError("AI response was not valid JSON or generation failed.") from e


async def create_resume_tool(
    gitingest_summary: str,
    gitingest_tree: str,
    gitingest_content: str,
    generation_id: str,
    project_name: str | None = None,
    job_description: str | None = None,
    websocket: WebSocket | None = None,
    model: str | None = None,
    custom_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Main tool to generate a resume section from repository analysis.

    Args:
        gitingest_summary: A summary of the repository from the ingestion tool.
        gitingest_tree: The directory structure of the repository.
        gitingest_content: Key file contents from the repository.
        generation_id: A unique ID for this generation request.
        project_name: An optional name for the project.
        job_description: An optional job description to tailor the output.
        websocket: An optional WebSocket for streaming status updates.
        model: Optional model override.
        custom_prompt: Optional custom prompt to override the default template.

    Returns:
        A dictionary containing the generated resume content or an error.
    """
    try:
        # Truncate job_description to avoid exceeding model context window
        max_job_desc_chars = 3000

        if job_description:
            # Normalize whitespace: replace multiple spaces/newlines/tabs with a single space
            job_description = re.sub(r"\s+", " ", job_description.strip())

            # Trim to max allowed length, optionally add ellipsis if content was cut
            if len(job_description) > max_job_desc_chars:
                job_description = job_description[:max_job_desc_chars].rstrip() + "..."

        # Truncate content to fit within context window limits
        max_chars = 30000
        content_truncated = len(gitingest_content) > max_chars
        truncated_content = gitingest_content[:max_chars] if content_truncated else gitingest_content

        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = _build_prompt(str(gitingest_summary), gitingest_tree, truncated_content, job_description)

        resume_data = await _generate_and_parse_response(prompt, model=model)

        corrected_data = await correct_resume_grammar(resume_data)

        # Ensure final data structure is sound
        final_result = {
            "success": True,
            "project_title": corrected_data.get("project_title", project_name or "N/A"),
            "tech_stack": corrected_data.get("tech_stack", []),
            "bullet_points": corrected_data.get("bullet_points", []),
            "additional_notes": corrected_data.get("additional_notes", ""),
            "future_plans": corrected_data.get("future_plans", ""),
            "potential_advancements": corrected_data.get("potential_advancements", ""),
            "interview_questions": corrected_data.get("interview_questions", []),
            "context_truncated": content_truncated,
        }
        await _emit_ws_message(websocket, "complete", "Generation successful!", generation_id)
        logger.info(f"Resume generation successful for generation ID: {generation_id}")
        return final_result

    except Exception as e:
        logger.critical(f"Resume generation failed for ID '{generation_id}': {e}", exc_info=True)
        await _emit_ws_message(websocket, "error", f"An unexpected error occurred: {e}", generation_id)
        return {"success": False, "error": str(e)}


async def generate_resume_from_data(
    repo_data: dict[str, Any],
    job_description: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for generate_resume_tool when you already have repo data."""
    return await create_resume_tool(
        gitingest_summary=repo_data.get("summary", ""),
        gitingest_tree=repo_data.get("tree", ""),
        gitingest_content=repo_data.get("content", ""),
        generation_id=f"cli_{os.urandom(4).hex()}",
        project_name=repo_data.get("project_name"),
        job_description=job_description,
        model=model,
        custom_prompt=prompt,
    )
