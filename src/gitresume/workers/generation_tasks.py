import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

from redis.asyncio import Redis

from gitresume.ai.litellm_client import LiteLLMResumeClient
from gitresume.core.config import get_settings
from gitresume.core.crypto import StringEncryptor
from gitresume.schemas.generation import GenerationStatus
from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.ingestion_service import RepositoryIngestionService
from gitresume.services.key_rotation import RedisProviderKeySelector
from gitresume.services.model_catalog import find_model_entry, model_mode_for, provider_for_model
from gitresume.services.oauth_provider_store import RedisOAuthProviderStore
from gitresume.services.repository_checkout_service import (
    RepositoryCheckout,
    RepositoryCheckoutService,
)
from gitresume.services.repository_service import GitHubRepositoryService
from gitresume.services.resume_generation_service import ResumeGenerationService
from gitresume.services.settings_store import RedisSettingsStore
from gitresume.workers.broker import broker

logger = logging.getLogger(__name__)


@broker.task
async def run_generation(generation_id: str) -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required to run generation jobs.")

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    service = RedisGenerationStateService(redis)
    checkout_service = RepositoryCheckoutService()
    checkout = None
    selected_key_secret: str | None = None
    current_stage = "generation"
    try:
        state = await service.get_generation(generation_id)
        if state is None:
            raise RuntimeError("Generation state not found.")
        github_token = await service.pop_github_token(generation_id)
        ephemeral_provider_api_key = await service.pop_provider_api_key(generation_id)
        current_stage = "repository validation"
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

        current_stage = "repository checkout"
        await service.append_event(
            generation_id,
            event_type="cloning",
            status=GenerationStatus.CLONING,
            message="Cloning repository",
        )
        checkout = await checkout_service.checkout(state.repository_url, github_token=github_token)

        current_stage = "repository analysis"
        await service.append_event(
            generation_id,
            event_type="analyzing",
            status=GenerationStatus.ANALYZING,
            message="Analyzing and packing repository context",
            data={"stage": "classifying-packing"},
        )
        context = await RepositoryIngestionService().build_context(checkout.local_path)
        repo_context = _resume_prompt_context(context, checkout)

        current_stage = "resume generation"
        await service.append_event(
            generation_id,
            event_type="generating",
            status=GenerationStatus.GENERATING,
            message="Generating resume",
        )
        selected_model = state.model or settings.ai_model
        if ephemeral_provider_api_key:
            selected_key_secret = ephemeral_provider_api_key
        elif _selected_model_uses_oauth(selected_model):
            if not settings.settings_encryption_key:
                raise RuntimeError("OAuth provider selection requires settings encryption.")
            oauth_store = RedisOAuthProviderStore(
                redis,
                StringEncryptor(settings.settings_encryption_key.get_secret_value()),
            )
            selected_key_secret = await oauth_store.select_access_token(
                state.oauth_provider_scope or "global",
                provider_for_model(selected_model),
            )
            if selected_key_secret is None:
                raise RuntimeError("OAuth provider is not connected.")
        elif state.provider_key_id is not None or getattr(settings, "allow_saved_byok", False):
            if not settings.settings_encryption_key:
                if state.provider_key_id is not None:
                    raise RuntimeError("Saved provider key selection requires settings encryption.")
            else:
                settings_store = RedisSettingsStore(
                    redis,
                    StringEncryptor(settings.settings_encryption_key.get_secret_value()),
                )
                selected_key = await RedisProviderKeySelector(redis, settings_store).select(
                    scope=state.provider_key_scope or "global",
                    provider=provider_for_model(selected_model),
                    model=selected_model,
                    provider_key_id=state.provider_key_id,
                )
                selected_key_secret = (
                    selected_key.secret.get_secret_value() if selected_key else None
                )
        result = await ResumeGenerationService(LiteLLMResumeClient(settings)).generate(
            repo_context=repo_context,
            job_description=state.job_description,
            model=selected_model,
            provider_api_key=selected_key_secret,
            model_mode=model_mode_for(selected_model),
        )
        await service.complete_generation(
            generation_id, result.model_dump(by_alias=True, mode="json")
        )
    except Exception as error:
        logger.warning(
            "Generation job failed generation_id=%s stage=%s exception_type=%s",
            generation_id,
            current_stage,
            type(error).__name__,
        )
        await service.fail_generation(generation_id, _public_failure_message(current_stage))
    finally:
        if checkout is not None:
            checkout_service.cleanup_checkout(checkout)
        await redis.aclose()


def _selected_model_uses_oauth(model: str) -> bool:
    entry = find_model_entry(model)
    return bool(entry and entry.auth_type == "oauth")


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


def _redact_secret(message: str, secret: str | None) -> str:
    if not secret:
        return message
    return message.replace(secret, "[redacted]")


def _redact_known_secrets(message: str, *secrets: str | None) -> str:
    redacted = message
    for secret in secrets:
        redacted = _redact_secret(redacted, secret)
    return redacted


def _public_failure_message(stage: str) -> str:
    return f"Generation failed during {stage}."
