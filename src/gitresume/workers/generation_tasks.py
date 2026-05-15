import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from redis.asyncio import Redis

from gitresume.ai.litellm_client import LiteLLMResumeClient
from gitresume.core.config import get_settings
from gitresume.schemas.generation import GenerationStatus
from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.ingestion_service import RepositoryIngestionService
from gitresume.services.repository_checkout_service import (
    RepositoryCheckout,
    RepositoryCheckoutService,
)
from gitresume.services.repository_service import GitHubRepositoryService
from gitresume.services.resume_generation_service import ResumeGenerationService
from gitresume.workers.broker import broker


@broker.task
async def run_generation(generation_id: str) -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required to run generation jobs.")

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    service = RedisGenerationStateService(redis)
    checkout_service = RepositoryCheckoutService()
    checkout = None
    try:
        state = await service.get_generation(generation_id)
        if state is None:
            raise RuntimeError("Generation state not found.")
        github_token = await service.pop_github_token(generation_id)
        await service.append_event(
            generation_id,
            event_type="validating",
            status=GenerationStatus.VALIDATING,
            message="Validating repository access",
            data={"repoUrl": state.repository_url},
        )
        validation = await GitHubRepositoryService().validate_access(
            state.repository_url, github_token=github_token
        )
        if not validation.get("success"):
            raise RuntimeError(
                str(validation.get("error_message") or "Repository validation failed.")
            )

        await service.append_event(
            generation_id,
            event_type="cloning",
            status=GenerationStatus.CLONING,
            message="Cloning repository",
        )
        checkout = await checkout_service.checkout(state.repository_url, github_token=github_token)

        await service.append_event(
            generation_id,
            event_type="analyzing",
            status=GenerationStatus.ANALYZING,
            message="Analyzing and packing repository context",
            data={"stage": "classifying-packing"},
        )
        context = await RepositoryIngestionService().build_context(checkout.local_path)
        repo_context = _resume_prompt_context(context, checkout)

        await service.append_event(
            generation_id,
            event_type="generating",
            status=GenerationStatus.GENERATING,
            message="Generating resume",
        )
        result = await ResumeGenerationService(LiteLLMResumeClient(settings)).generate(
            repo_context=repo_context,
            job_description=state.job_description,
        )
        await service.complete_generation(
            generation_id, result.model_dump(by_alias=True, mode="json")
        )
    except Exception as error:
        await service.fail_generation(generation_id, str(error))
    finally:
        if checkout is not None:
            checkout_service.cleanup_checkout(checkout)
        await redis.aclose()


def _resume_prompt_context(context: dict[str, object], checkout: RepositoryCheckout) -> str:
    payload = {
        "repository": {
            "owner": checkout.owner,
            "name": checkout.name,
            "full_name": checkout.full_name,
            "canonical_url": checkout.canonical_url,
        },
        "analysis": context,
    }
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True)


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
