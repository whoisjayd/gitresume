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
from typing import Dict, Any, Optional, List

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

{user_context}

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

### **Prioritization Hierarchy (Weighted Scoring System)**
**CRITICAL: Rank achievements by weighted impact score, NOT by chronological order or recency**

1. **QUANTIFIABLE IMPACT & RESULTS (40% weight)** - Measurable improvements with specific metrics
   - Performance gains (X% faster, Y% reduction in load time, Z% improved throughput)
   - Scale achievements (handled X users, processed Y transactions, managed Z data volume)
   - Cost savings or efficiency gains (reduced X% operational costs, saved Y hours, eliminated Z manual processes)
   - Quality improvements (reduced X% bugs, increased Y% test coverage, improved Z% reliability)

2. **IMPLEMENTATION DIFFICULTY & TECHNICAL COMPLEXITY (30% weight)** - Advanced technical challenges
   - Architectural complexity (distributed systems, microservices, complex integrations)
   - Algorithm sophistication (ML models, optimization algorithms, complex data structures)
   - Technical innovation (novel approaches, cutting-edge technologies, research-level work)
   - Cross-system integration complexity (multiple APIs, legacy system modernization)

3. **BUSINESS & USER IMPACT (20% weight)** - Real-world value and problem-solving significance
   - User experience transformations (improved usability, accessibility, feature adoption)
   - Critical system improvements (security enhancements, disaster recovery, compliance)
   - Business process automation (workflow optimization, manual task elimination)
   - Strategic technical decisions (technology migration, platform modernization)

4. **ATS & KEYWORD OPTIMIZATION (10% weight)** - Resume scanning and job alignment
   - Job description keyword alignment and technical terminology matching
   - Industry-standard technology stack demonstration
   - Professional development practices (CI/CD, testing, documentation)
   - Engineering excellence indicators (code quality, maintainability, best practices)

### **Achievement Ranking Guidelines**
- **Tier 1 (Highest Priority)**: Quantifiable + High Complexity + High Impact
- **Tier 2 (High Priority)**: Strong Quantifiable Results OR High Technical Complexity
- **Tier 3 (Medium Priority)**: Moderate Impact with ATS optimization
- **Exclude**: Low-impact changes, simple fixes, routine maintenance (regardless of recency)

### **Writing Standards**
- **QUANTIFIABLE FIRST**: ALWAYS prioritize measurable results - percentages, numbers, scale indicators, time savings, performance improvements
- **Technical Complexity Indicators**: Use terms that convey difficulty - "architected," "engineered," "optimized," "scaled," "automated," "integrated"
- **Impact-Driven Language**: Begin with powerful verbs that show significant contribution and technical depth
- **Metrics Integration**: Include specific numbers wherever possible (X% improvement, Y users supported, Z systems integrated)
- **Technical Sophistication**: Demonstrate advanced engineering concepts and architectural thinking
- **Problem-Solution-Impact**: Structure as Challenge → Technical Solution → Quantifiable Result
- **ATS Optimization**: Use industry-standard terminology and relevant technical keywords from job requirements
- **Confidentiality First**: Focus on technical impact and improvements rather than specific business logic or proprietary implementation details
- **Generic Technical Language**: Use terms like "enhanced system performance," "improved error handling," "optimized data processing" instead of specific method names or business rules
- **Plain Text Format**: Simple strings only - no nested objects or complex structures
- **STAR Method Integration**: Incorporate Situation, Task, Action, Result naturally within narrative flow
- Do not include any personal information, such as names, contact details, or locations.
- DO not use personal pronouns like "I" or "we". Write in the third person.

### **Content Requirements**
- Extract achievements from **technical patterns and improvement types** rather than specific code implementations
- Highlight **architectural approaches and problem-solving methodologies** without revealing proprietary logic
- Showcase **engineering excellence and technical impact** while maintaining confidentiality
- Demonstrate **proficiency with technology stacks and development practices** used
- Reflect **measurable outcomes and system improvements** in general terms
- **Privacy-Conscious Analysis**: When commit data is available, focus on the TYPE of improvements made (performance, security, maintainability) rather than specific implementation details

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
Generate **valid JSON only** with no additional commentary, explanations, or formatting. 

**CRITICAL RANKING METHODOLOGY:**
1. **Score each achievement** using weighted criteria: Quantifiable Impact (40%) + Technical Complexity (30%) + Business Impact (20%) + ATS Relevance (10%)
2. **Prioritize measurable results** - include specific percentages, numbers, scale indicators, time savings, performance improvements
3. **Rank by impact score** NOT chronological order - ignore commit dates and recency
4. **Lead with metrics** - start bullet points with quantifiable results whenever possible
5. **Focus on technical sophistication** - emphasize advanced engineering, architecture, and complex problem-solving

**BULLET POINT FORMULA:** Technical Action + Quantifiable Metric + Business/Technical Impact

Every bullet point must reflect genuine, implemented functionality that demonstrates professional-level software engineering capabilities with measurable outcomes.
""".strip()

# --- AI Model Initialization ---
# Only use the primary AI provider, no fallbacks
PRIMARY_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()


def redact_sensitive_prompt_data(prompt: str, max_length: int = 1000) -> str:
    """
    Redact sensitive information from prompt before sending to client.
    
    Args:
        prompt: The full prompt string
        max_length: Maximum length of redacted prompt
        
    Returns:
        Sanitized prompt safe for client transmission
    """
    import re
    
    # Remove potential sensitive patterns
    sensitive_patterns = [
        # Email addresses
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]'),
        # URLs with potential sensitive info
        (r'https?://[^\s]+', '[URL_REDACTED]'),
        # API keys (common patterns)
        (r'["\']?[A-Za-z0-9]{20,}["\']?', '[KEY_REDACTED]'),
        # File paths that might contain usernames
        (r'[A-Za-z]:\\[^\\]+\\[^\\]+', '[PATH_REDACTED]'),
        # Potential secrets or tokens
        (r'(?i)(secret|token|key|password|auth)["\']?\s*[:=]\s*["\']?[A-Za-z0-9+/=]{10,}', '[SECRET_REDACTED]'),
    ]
    
    redacted_prompt = prompt
    for pattern, replacement in sensitive_patterns:
        redacted_prompt = re.sub(pattern, replacement, redacted_prompt)
    
    # Truncate to safe length
    if len(redacted_prompt) > max_length:
        redacted_prompt = redacted_prompt[:max_length] + "... [TRUNCATED FOR SECURITY]"
    
    return redacted_prompt


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
            f"Primary AI provider '{PRIMARY_PROVIDER}' could not be initialized. Check API key environment variables.")

    return factories


CLIENT_FACTORIES = get_client_factories()


async def _emit_ws_message(websocket: Optional[WebSocket], msg_type: str, content: Any, generation_id: str):
    """Safely sends a message over a WebSocket connection."""
    if not websocket or websocket.client_state != WebSocketState.CONNECTED:
        return
    try:
        message = {
            "type": msg_type,
            "content": content,
            "generation_id": generation_id
        }
        await websocket.send_json(message)
    except Exception as e:
        logger.warning(f"WebSocket send error: {e}")


def _build_prompt(gitingest_summary: str, gitingest_tree: str, gitingest_content: str,
                  job_description: Optional[str], user_stats: Optional[Dict[str, Any]] = None) -> str:
    """Constructs the final prompt for the AI model."""
    # Determine if this is user-specific analysis
    is_user_specific = user_stats is not None and bool(user_stats)
    
    # Log basic info to server (keep minimal)
    logger.info(f"Building prompt - User-specific: {is_user_specific}")
    if is_user_specific and user_stats:
        logger.info(f"User stats: {user_stats.get('total_commits', 0)} commits, {user_stats.get('lines_added', 0)} lines added")
        
    job_desc_text = f"The user is applying for a job with this description: {job_description.strip()}" if job_description else "N/A"
    
    # Build user-specific context if available
    user_context = ""
    if user_stats:
        user_context = f"""

🎯 CRITICAL: This analysis represents ONLY the authenticated user's personal contributions to this project.

USER'S CONTRIBUTION METRICS:
- Personal commits made: {user_stats.get('total_commits', 0)}
- Lines of code added: {user_stats.get('lines_added', 0)}
- Lines of code modified/deleted: {user_stats.get('lines_deleted', 0)}
- Files personally modified: {user_stats.get('files_modified', 0)}
- Programming languages used: {', '.join(user_stats.get('languages', []))}

📝 COMMIT ANALYSIS METHODOLOGY:
The implementation details section includes the user's code contributions, but maintain confidentiality by:

⭐ WEIGHTED SCORING FOR ACHIEVEMENT RANKING (IGNORE CHRONOLOGICAL ORDER):

🏆 TIER 1 ACHIEVEMENTS (Highest Priority - Include These First):
✅ QUANTIFIABLE IMPACT (40% weight): Look for measurable improvements in commit patterns
   - Performance metrics: "Optimized algorithm reducing execution time by X%"
   - Scale achievements: "Enhanced system to handle X concurrent users"
   - Efficiency gains: "Automated process eliminating X hours of manual work"
   - Quality improvements: "Implemented testing increasing coverage by X%"

✅ TECHNICAL COMPLEXITY (30% weight): Identify sophisticated engineering challenges
   - Multi-system integration across X platforms
   - Complex algorithm implementation (ML, optimization, data processing)
   - Architectural decisions for scalability and maintainability
   - Advanced technology adoption and implementation

🥈 TIER 2 ACHIEVEMENTS (High Priority):
✅ HIGH IMPACT + MODERATE COMPLEXITY: Significant business value with solid technical depth
✅ HIGH COMPLEXITY + MODERATE IMPACT: Advanced technical work with measurable results

🥉 TIER 3 ACHIEVEMENTS (Include if space allows):
✅ MODERATE IMPACT + ATS OPTIMIZATION: Good technical work with job-relevant keywords

❌ EXCLUDE (Regardless of Recency):
❌ Simple bug fixes, routine maintenance, minor updates
❌ Low-impact changes without measurable results
❌ Basic feature implementations without complexity or quantifiable outcomes

ANALYSIS APPROACH FOR USER COMMITS:
1. Calculate technical complexity score based on files modified, lines changed, and improvement type
2. Identify quantifiable metrics from commit patterns (performance, scale, efficiency)
3. Assess business impact level (critical systems, user experience, operational efficiency)
4. Rank achievements by weighted score, NOT by timeline or commit date
5. Extract specific numbers and percentages wherever possible from technical analysis

CONFIDENTIALITY REQUIREMENTS:
❌ Do NOT expose specific business logic, proprietary algorithms, or sensitive implementation details
❌ Do NOT include actual code snippets, variable names, or method signatures in bullet points
❌ Do NOT reveal specific domain knowledge, business rules, or proprietary workflows
❌ Avoid mentioning specific client names, internal project names, or confidential features

BULLET POINT RANKING METHODOLOGY:
1. Score each potential achievement: (Quantifiable Impact × 40%) + (Technical Complexity × 30%) + (Business Impact × 20%) + (ATS Relevance × 10%)
2. Rank by weighted score and select top 5 achievements regardless of commit date or recency
3. ALWAYS lead with specific metrics and quantifiable results when available
4. Structure as: "Technical Action + Quantifiable Result + Impact/Benefit"

EXAMPLES OF PREFERRED BULLET POINT FORMATS:
✅ "Engineered distributed caching system reducing API response time by 65% and supporting 10x user load"
✅ "Architected microservices infrastructure handling 1M+ daily transactions with 99.9% uptime"
✅ "Optimized database queries improving application performance by 40% and reducing server costs by $2K/month"
✅ "Implemented automated testing pipeline increasing code coverage from 60% to 95% and reducing bugs by 80%"

Use metrics from user stats: "{user_stats.get('total_commits', 0)} commits across {user_stats.get('files_modified', 0)} files, {user_stats.get('lines_added', 0)} lines contributed"
Focus on MEASURABLE IMPACT and TECHNICAL SOPHISTICATION over chronological order.
"""
    
    # Build the final prompt using proper templating with placeholders
    final_prompt = RESUME_PROMPT_TEMPLATE.format(
        user_context=user_context,
        job_description=job_desc_text,
        gitingest_summary=gitingest_summary,
        gitingest_tree=gitingest_tree,
        gitingest_content=gitingest_content,
    )
    
    # Minimal server logging
    logger.info(f"Generated prompt - Length: {len(final_prompt)} chars, User-specific: {user_stats is not None}")
    
    return final_prompt


async def _generate_and_parse_response(prompt: str) -> Dict[str, Any]:
    """Calls the AI model and parses the JSON response."""
    full_response_text = ""

    async def operation(client):
        """Defines the specific API call for the AI model."""
        provider = client.__class__.__module__.split('.')[0]
        if provider == 'google':  # Gemini
            response = await client.generate_content_async(prompt)
            yield response.text
        else:  # OpenAI, Groq, Anthropic (Claude) like
            # This simplified structure works for OpenAI, Groq, and Claude v2 messages
            if provider == 'anthropic':
                messages = [{"role": "user", "content": prompt}]
                max_tokens = 4096
                response = await client.messages.create(
                    model=os.getenv("CLAUDE_MODEL_VERSION", "claude-3-opus-20240229"), messages=messages,
                    max_tokens=max_tokens)
                yield response.content[0].text
            else:
                model_map = {"openai": "gpt-4-turbo", "groq": "llama3-70b-8192"}
                response = await client.chat.completions.create(
                    model=model_map.get(provider, "default-model"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                yield response.choices[0].message.content

    # This will try the primary provider, then fall back to others if needed.
    async for chunk in execute_with_retry(operation, CLIENT_FACTORIES):
        full_response_text += chunk

    # Clean and parse the JSON response
    try:
        json_str = full_response_text.strip()
        # Find the JSON block within ```json ... ```
        match = re.search(r'```json\s*(\{.*?\})\s*```', json_str, re.DOTALL)
        if match:
            json_str = match.group(1)
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to decode JSON from AI response. Error: {e}. Response text: '{full_response_text[:500]}...'")
        raise ValueError("AI response was not valid JSON.") from e


async def create_resume_tool(
        gitingest_summary: str,
        gitingest_tree: str,
        gitingest_content: str,
        generation_id: str,
        project_name: Optional[str] = None,
        job_description: Optional[str] = None,
        websocket: Optional[WebSocket] = None,
        user_stats: Optional[Dict[str, Any]] = None,
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
        user_stats: Optional user contribution statistics when analyzing user-specific commits.

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
            job_description = re.sub(r'\s+', ' ', job_description.strip())

            # Trim to max allowed length, optionally add ellipsis if content was cut
            if len(job_description) > max_job_desc_chars:
                job_description = job_description[:max_job_desc_chars].rstrip() + "..."

        # Truncate content to fit within context window limits
        max_chars = 30000
        content_truncated = len(gitingest_content) > max_chars
        truncated_content = gitingest_content[:max_chars] if content_truncated else gitingest_content

        prompt = _build_prompt(str(gitingest_summary), gitingest_tree, truncated_content, job_description, user_stats)

        # Send prompt details to browser console via WebSocket (with sensitive data redacted)
        if websocket:
            is_user_specific = user_stats is not None and bool(user_stats)
            # Redact sensitive information before sending to client
            safe_prompt = redact_sensitive_prompt_data(prompt, max_length=2000)
            prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
            safe_preview = redact_sensitive_prompt_data(prompt_preview, max_length=500)
            
            prompt_info = {
                "type": "prompt_debug",
                "generation_id": generation_id,
                "data": {
                    "is_user_specific": is_user_specific,
                    "prompt_length": len(prompt),
                    "content_truncated": content_truncated,
                    "user_stats": user_stats if user_stats else None,
                    "prompt_preview": safe_preview,
                    "full_prompt": safe_prompt  # Redacted version for security
                }
            }
            try:
                await websocket.send_text(json.dumps(prompt_info))
            except Exception as e:
                logger.warning(f"Failed to send prompt debug info: {e}")

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
