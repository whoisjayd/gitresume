"""
Core tool for generating a resume section from repository analysis.

This module orchestrates the process of taking repository data,
generating a detailed resume section using an AI model, and then
refining the output with grammar correction.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from .api_utils import APIClientFactory, execute_with_retry
from .grammar_check import correct_resume_grammar

logger = logging.getLogger(__name__)

# --- Configuration and Constants ---

# The prompt is critical. It's defined as a constant for clarity and maintainability.
# It instructs the LLM to act as an expert and provides a strict JSON output format.
RESUME_PROMPT_TEMPLATE = """
You are an elite technical resume strategist and senior software engineering consultant with expertise in ATS optimization and technical storytelling. Your task is to perform deep codebase analysis and generate a compelling, data-driven resume section that showcases real technical achievements.

## 🎯 Core Mission
Transform raw codebase analysis into high-impact professional narrative by identifying and articulating the most impressive technical contributions, architectural decisions, and engineering solutions implemented in the project.

## 📋 Required Output Format (Strict JSON)
```json
{{
    "project_title": "Concise, professional project name that reflects core functionality",
    "tech_stack": ["Technology names only - no versions, no descriptions"],
    "bullet_points": [
        "Achievement-focused bullet point demonstrating technical excellence",
        "Impact-driven statement with quantifiable results where possible",
        "Architecture or optimization accomplishment with technical depth",
        "Innovation or problem-solving highlight with business value",
        "Additional technical contribution showcasing expertise"
    ],
    "additional_notes": "Unique technical setup, deployment strategies, or noteworthy engineering decisions",
    "future_plans": "Logical next features or enhancements based on current codebase state",
    "potential_advancements": "Advanced architectural improvements, performance optimizations, or scalability enhancements",
    "interview_questions": [
        {{
            "question": "Deep technical question about specific implementation details",
            "answer": "Comprehensive response demonstrating mastery of the technology and reasoning behind decisions",
            "category": "Technical"
        }},
        {{
            "question": "Behavioral question related to team dynamics or project challenges",
            "answer": "Insightful answer reflecting on past experiences and lessons learned",
            "category": "Behavioral"
        }},
        {{....}}
    ]
}}
```

## 🚀 Bullet Point Excellence Framework

### **Prioritization Hierarchy (Most Important First)**
1. **Technical Innovation & Complexity** - Novel algorithms, advanced patterns, sophisticated architectures
2. **Performance & Scale Impact** - Measurable improvements, optimization results, capacity enhancements
3. **Business & User Value** - Real-world problem solving, feature impact, user experience improvements
4. **Engineering Excellence** - Code quality, maintainability, testing, documentation, DevOps practices
5. Make sure that if job description is provided, the bullet points are tailored to align with the job requirements.
6. Key words from the job description should be naturally integrated into the bullet points.

### **Writing Standards**
- **Action-Driven Language**: Begin with powerful technical verbs (Architected, Engineered, Optimized, Implemented, Automated, Streamlined)
- **Quantifiable Impact**: Include metrics, percentages, performance gains, scale indicators whenever possible
- **Technical Depth**: Demonstrate understanding of underlying technologies and engineering principles
- **Plain Text Format**: Simple strings only - no nested objects or complex structures
- **STAR Method Integration**: Incorporate Situation, Task, Action, Result naturally within narrative flow
- **ATS Optimization**: Use industry-standard terminology and relevant technical keywords
- Do not include any personal information, such as names, contact details, or locations.
- DO not use personal pronouns like "I" or "we". Write in the third person.

### **Content Requirements**
- Extract achievements from **actual implemented code and features**
- Highlight **real architectural decisions and technical challenges solved**
- Showcase **genuine problem-solving and engineering judgment**
- Demonstrate **proficiency with the specific technology stack used**
- Reflect **measurable outcomes and technical improvements**

## 🎯 Interview Preparation Framework

### **Question Generation Strategy**
- **5-10 comprehensive questions** covering both technical depth and behavioral scenarios
- **Technical Deep-Dives**: Architecture decisions, algorithm choices, performance considerations, debugging approaches
- **Design & Trade-offs**: Technology selection rationale, scalability planning, security considerations
- **Problem-Solving Scenarios**: Real challenges encountered, optimization strategies, maintenance approaches
- **Future-Focused**: Enhancement possibilities, scalability improvements, technology evolution

### **Answer Quality Standards**
- **Technical Precision**: Accurate, detailed explanations demonstrating genuine understanding
- **Decision Rationale**: Clear reasoning behind implementation choices and trade-offs considered
- **Practical Experience**: Real-world context and lessons learned from the project
- **Growth Mindset**: Acknowledgment of limitations and areas for future improvement

## 📊 Analysis Input Sources
- **Codebase Summary**: `{gitingest_summary}`
- **Project Structure**: `{gitingest_tree}`
- **Implementation Details**: `{gitingest_content}`
- **Target Role Context**: `{job_description}`

## ⚡ Final Instructions
Generate **valid JSON only** with no additional commentary, explanations, or formatting. Focus on extracting and articulating the most compelling technical narrative from the actual codebase provided. Every bullet point must reflect genuine, implemented functionality that demonstrates professional-level software engineering capabilities.
""".strip()

# --- AI Model Initialization ---
# Only use the primary AI provider, no fallbacks
PRIMARY_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()


def get_client_factories() -> List[APIClientFactory]:
    """Initializes and returns a list of client factories, only primary."""
    factories = []

    def _create_factory(provider: str) -> Optional[APIClientFactory]:
        keys = os.getenv(f"{provider.upper()}_API_KEYS", "")
        premium_key = os.getenv(f"{provider.upper()}_PREMIUM_API_KEY", "")
        if keys or premium_key:
            try:
                return APIClientFactory(provider, keys, premium_key)
            except Exception as e:
                logger.error(f"Failed to initialize factory for '{provider}': {e}")
        return None

    primary_factory = _create_factory(PRIMARY_PROVIDER)
    if primary_factory:
        factories.append(primary_factory)
        logger.info(f"Primary AI provider '{PRIMARY_PROVIDER}' initialized.")
    else:
        logger.error(
            f"Primary AI provider '{PRIMARY_PROVIDER}' could not be initialized. Check API key environment variables."
        )

    return factories


CLIENT_FACTORIES = get_client_factories()


async def _emit_ws_message(websocket: Optional[WebSocket], msg_type: str, content: Any, generation_id: str):
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
    job_description: Optional[str],
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


async def _generate_and_parse_response(prompt: str) -> Dict[str, Any]:
    """Calls the AI model and parses the JSON response."""
    full_response_text = ""

    async def operation(client):
        """Defines the specific API call for the AI model."""
        provider = client.__class__.__module__.split(".")[0]
        if provider == "google":  # Gemini
            response = await client.generate_content_async(prompt)
            yield response.text
        else:  # OpenAI, Groq, Anthropic (Claude) like
            # This simplified structure works for OpenAI, Groq, and Claude v2 messages
            if provider == "anthropic":
                messages = [{"role": "user", "content": prompt}]
                max_tokens = 4096
                response = await client.messages.create(
                    model=os.getenv("CLAUDE_MODEL_VERSION", "claude-3-opus-20240229"),
                    messages=messages,
                    max_tokens=max_tokens,
                )
                yield response.content[0].text
            else:
                model_map = {"openai": "gpt-4-turbo", "groq": "llama3-70b-8192"}
                response = await client.chat.completions.create(
                    model=model_map.get(provider, "default-model"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                yield response.choices[0].message.content

    # This will try the primary provider, then fall back to others if needed.
    async for chunk in execute_with_retry(operation, CLIENT_FACTORIES):
        full_response_text += chunk

    # Clean and parse the JSON response
    try:
        json_str = full_response_text.strip()
        # Find the JSON block within ```json ... ```
        match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
        if match:
            json_str = match.group(1)
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to decode JSON from AI response. Error: {e}. Response text: '{full_response_text[:500]}...'"
        )
        raise ValueError("AI response was not valid JSON.") from e


async def create_resume_tool(
    gitingest_summary: str,
    gitingest_tree: str,
    gitingest_content: str,
    generation_id: str,
    project_name: Optional[str] = None,
    job_description: Optional[str] = None,
    websocket: Optional[WebSocket] = None,
) -> Dict[str, Any]:
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

    Returns:
        A dictionary containing the generated resume content or an error.
    """
    if not CLIENT_FACTORIES:
        return {"success": False, "error": "AI service not configured. Check API keys."}

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

        prompt = _build_prompt(str(gitingest_summary), gitingest_tree, truncated_content, job_description)

        resume_data = await _generate_and_parse_response(prompt)

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
