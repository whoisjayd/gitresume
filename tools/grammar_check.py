"""
Grammar and style correction services.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Dict, List

from .api_utils import APIClientFactory, execute_with_retry

logger = logging.getLogger(__name__)

LOW_COST_MODELS = {
    "gemini": "gemini-2.0-flash-lite",
    "openai": "gpt-3.5-turbo",
    "groq": "llama3-8b-8192",
    "claude": "claude-3-haiku-20240307",
}

GRAMMAR_PROVIDER = os.getenv("GRAMMAR_PROVIDER", "gemini").lower()
text_processor = None


class LocalGrammarFixer:
    @staticmethod
    def fix_spacing_and_punctuation(text: str) -> str:
        if not text:
            return text
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)
        text = re.sub(r"([.,;:!?])(?=[a-zA-Z0-9])", r"\1 ", text)
        text = re.sub(r"\.([A-Z])", r". \1", text)
        return text.strip()


class AIGrammarChecker:
    def __init__(self, client_factory: APIClientFactory):
        self.client_factory = client_factory
        self.provider = client_factory.provider
        self.model_version = LOW_COST_MODELS.get(self.provider)

    async def correct_text_async(self, text: str) -> str:
        if not text or not text.strip():
            return text
        prompt = f"""You are a professional grammar and writing assistant. Your task is to correct grammar, spelling, and spacing issues in the provided text while preserving the original meaning and technical terminology.
                RULES:
                1. Fix grammatical errors, spelling mistakes, and spacing issues
                2. Preserve all technical terms, variable names, and domain-specific vocabulary
                3. Maintain the original tone and style
                4. Fix word spacing issues where words are incorrectly combined (e.g., "webapplication" → "web application")
                5. Do NOT change the meaning or add new information
                6. Return ONLY the corrected text, no explanations or formatting
                Text to correct: {text}
                Corrected text"""

        async def operation(client) -> AsyncGenerator[str, None]:
            if self.provider == "gemini":
                response = await client.generate_content_async(prompt)
                yield response.text.strip() if response.text else text
            elif self.provider in ["openai", "groq"]:
                model_map = {"openai": "gpt-4-turbo", "groq": "llama3-70b-8192"}
                response = await client.chat.completions.create(
                    model=model_map.get(self.provider, self.model_version),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=2048,
                )
                yield (response.choices[0].message.content.strip() if response.choices else text)
            elif self.provider == "claude":
                response = await client.messages.create(
                    model=self.model_version,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=2048,
                )
                yield response.content[0].text.strip() if response.content else text

        try:
            async for corrected_text in execute_with_retry(
                operation, [self.client_factory], max_retries_per_provider=2
            ):
                return corrected_text
            return text
        except Exception as e:
            logger.warning(f"AI grammar correction failed for '{self.provider}': {e}. Returning original text.")
            return text


@dataclass
class TextProcessingJob:
    text: str
    update_func: Callable[[str], None]

    async def process(self, checker: AIGrammarChecker, semaphore: asyncio.Semaphore):
        async with semaphore:
            corrected_text = await checker.correct_text_async(self.text)
            self.update_func(corrected_text)


class ConcurrentTextProcessor:
    def __init__(self, checker: AIGrammarChecker, concurrency_limit: int = 5):
        self.checker = checker
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def process_jobs(self, jobs: List[TextProcessingJob]):
        if not jobs:
            return
        tasks = [job.process(self.checker, self.semaphore) for job in jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error in text processing job {i}: {result}")


def initialize_grammar_checker():
    global text_processor
    try:
        keys = os.getenv(f"{GRAMMAR_PROVIDER.upper()}_API_KEYS", "")
        premium_key = os.getenv(f"{GRAMMAR_PROVIDER.upper()}_PREMIUM_API_KEY", "")
        if keys or premium_key:
            factory = APIClientFactory(GRAMMAR_PROVIDER, keys, premium_key)
            checker = AIGrammarChecker(factory)
            text_processor = ConcurrentTextProcessor(checker)
            logger.info(f"Initialized AI grammar checker with provider: '{GRAMMAR_PROVIDER}'")
        else:
            logger.warning(f"No API keys for grammar provider '{GRAMMAR_PROVIDER}'. AI grammar check disabled.")
    except Exception as e:
        logger.error(f"Failed to initialize AI grammar checker: {e}")


initialize_grammar_checker()


async def correct_resume_grammar(resume_data: Dict[str, Any]) -> Dict[str, Any]:
    if not text_processor:
        logger.warning("AI text processor not available. Applying basic local fixes.")
        for key, value in resume_data.items():
            if isinstance(value, str):
                resume_data[key] = LocalGrammarFixer.fix_spacing_and_punctuation(value)
            elif isinstance(value, list) and key == "bullet_points":
                resume_data[key] = [LocalGrammarFixer.fix_spacing_and_punctuation(str(v)) for v in value]
        return resume_data

    texts_to_correct = []
    update_callbacks = []
    separator = "\n<--SEP-->\n"

    # Gather all text fields into a single list for batch processing
    for field in [
        "project_title",
        "additional_notes",
        "future_plans",
        "potential_advancements",
    ]:
        if resume_data.get(field) and isinstance(resume_data[field], str) and resume_data[field].strip():
            texts_to_correct.append(resume_data[field])
            update_callbacks.append(lambda text, f=field: resume_data.__setitem__(f, text))

    if isinstance(resume_data.get("bullet_points"), list):
        for i, bullet in enumerate(resume_data["bullet_points"]):
            if isinstance(bullet, str) and bullet.strip():
                texts_to_correct.append(bullet)
                update_callbacks.append(
                    lambda text, index=i: resume_data["bullet_points"].__setitem__(index, text.strip())
                )

    if isinstance(resume_data.get("interview_questions"), list):
        for i, item in enumerate(resume_data["interview_questions"]):
            if isinstance(item, dict):
                if item.get("question") and item["question"].strip():
                    texts_to_correct.append(item["question"])
                    update_callbacks.append(
                        lambda text, index=i: resume_data["interview_questions"][index].__setitem__(
                            "question", text.strip()
                        )
                    )
                if item.get("answer") and item["answer"].strip():
                    texts_to_correct.append(item["answer"])
                    update_callbacks.append(
                        lambda text, index=i: resume_data["interview_questions"][index].__setitem__(
                            "answer", text.strip()
                        )
                    )
    if not texts_to_correct:
        logger.info("No text found for grammar correction.")
        return resume_data

    combined_text = separator.join(texts_to_correct)

    def update_all(corrected_text):
        corrected_items = corrected_text.split(separator)
        if len(corrected_items) == len(texts_to_correct):
            for i, corrected_item in enumerate(corrected_items):
                update_callbacks[i](corrected_item)
        else:
            logger.warning(
                f"Corrected items count mismatch. Expected {len(texts_to_correct)}, got {len(corrected_items)}. Skipping update."
            )

    job = TextProcessingJob(text=combined_text, update_func=update_all)

    logger.info(f"Starting grammar correction for {len(texts_to_correct)} text chunks in a single batch...")
    await text_processor.process_jobs([job])
    logger.info("Grammar correction complete.")
    return resume_data
