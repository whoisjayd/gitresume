import logging
import os
from typing import Any, Dict, List, Optional

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Enable disk caching for LiteLLM
try:
    litellm.cache = litellm.Cache(type="disk")
    logger.info("LiteLLM disk cache enabled")
except Exception as e:
    logger.warning(f"Failed to initialize LiteLLM cache: {e}")

class UnifiedLLMClient:
    """
    Unified client for LLM completions using LiteLLM.
    Replaces the previous multi-provider factory approach.
    """

    def __init__(self, default_model: Optional[str] = None):
        self.default_model = default_model or os.getenv("AI_MODEL", "gemini/gemini-2.0-flash-lite")
        # Ensure API keys are available in environment as LiteLLM expects them
        # (e.g., OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Generate a completion using LiteLLM with retries.
        """
        target_model = model or self.default_model

        try:
            response = await litellm.acompletion(
                model=target_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LiteLLM completion failed for model {target_model}: {e}")
            raise

    async def generate_json_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a completion and ensure it's parsed as JSON.
        """
        import json
        import re

        # For some models, we might need to force JSON mode or provide a schema
        # LiteLLM handles many of these nuances
        response_text = await self.generate_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            **kwargs
        )

        try:
            # Try direct parsing
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Fallback: find JSON block
            match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

            # Last resort: try to find anything that looks like JSON
            match = re.search(r"(\{.*\})", response_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

            logger.error(f"Failed to parse JSON from response: {response_text[:500]}")
            raise ValueError("LLM response was not valid JSON")

# Global instance for easy access
llm_client = UnifiedLLMClient()
