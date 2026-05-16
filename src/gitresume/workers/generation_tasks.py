import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

from redis.asyncio import Redis

from gitresume.ai.litellm_client import LiteLLMResumeClient
from gitresume.core.config import get_settings
from gitresume.core.crypto import StringEncryptor
from gitresume.schemas.generation import GenerationStatus
from gitresume.services.contribution_analysis_service import ContributionAnalysisService
from gitresume.services.generation_state_service import RedisGenerationStateService
from gitresume.services.ingestion_service import RepositoryIngestionService
from gitresume.services.key_rotation import RedisProviderKeySelector
from gitresume.services.model_catalog import find_model_entry, model_mode_for, provider_for_model
from gitresume.services.oauth_provider_store import RedisOAuthProviderStore
from gitresume.services.repository_checkout_service import (
    RepositoryCheckout,
    RepositoryCheckoutService,
)
from gitresume.services.repository_investigation_service import RepositoryInvestigationService
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
        if github_token is None:
            configured_token = (
                getattr(settings, "github_token", None)
                if getattr(settings, "app_mode", "self_hosted") == "self_hosted"
                else None
            )
            github_token = _secret_value(configured_token)
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

        selected_model = state.model or settings.ai_model
        current_stage = "provider key selection"
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
                    scope=_provider_key_selection_scope(state, settings),
                    provider=provider_for_model(selected_model),
                    model=selected_model,
                    provider_key_id=state.provider_key_id,
                )
                selected_key_secret = (
                    selected_key.secret.get_secret_value() if selected_key else None
                )
        if getattr(settings, "enable_guided_analysis", False):
            current_stage = "repository investigation"
            contribution_context = None
            allowed_paths = None
            investigation_initial_context: dict[str, object] | str = context
            if getattr(settings, "enable_contribution_analysis", False) and state.analysis_author:
                contribution_analysis = ContributionAnalysisService().analyze(
                    checkout.local_path,
                    author=state.analysis_author,
                    days=state.analysis_days
                    or getattr(settings, "contribution_analysis_default_days", 300),
                    max_commits=getattr(settings, "contribution_analysis_max_commits", 100),
                    max_files=getattr(settings, "contribution_analysis_max_files", 500),
                )
                contribution_context = contribution_analysis.to_prompt_context()
                allowed_paths = set(contribution_analysis.touched_files)
                repo_context = _author_scoped_resume_prompt_context(
                    contribution_context, allowed_paths, checkout
                )
                investigation_initial_context = contribution_context
            await service.append_event(
                generation_id,
                event_type="analyzing",
                status=GenerationStatus.ANALYZING,
                message="Investigating repository evidence",
                data=_guided_analysis_event_data(state, allowed_paths),
            )
            try:
                evidence_brief = await RepositoryInvestigationService().investigate(
                    repo_root=checkout.local_path,
                    initial_context=investigation_initial_context,
                    ai_client=LiteLLMResumeClient(settings),
                    model=selected_model,
                    provider_api_key=selected_key_secret,
                    model_mode=model_mode_for(selected_model),
                    max_actions=getattr(settings, "guided_analysis_max_actions", 6),
                    max_chars_per_observation=getattr(
                        settings, "guided_analysis_max_chars_per_observation", 4_000
                    ),
                    max_observations=getattr(settings, "guided_analysis_max_observations", 6),
                    allowed_paths=allowed_paths,
                    contribution_context=contribution_context,
                )
                repo_context = _guided_resume_prompt_context(evidence_brief, checkout)
            except Exception as investigation_error:
                logger.warning(
                    "Guided repository investigation failed generation_id=%s exception_type=%s",
                    generation_id,
                    type(investigation_error).__name__,
                )

        current_stage = "resume generation"
        await service.append_event(
            generation_id,
            event_type="generating",
            status=GenerationStatus.GENERATING,
            message="Generating resume",
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
            try:
                checkout_service.cleanup_checkout(checkout)
            except Exception as cleanup_error:
                logger.warning(
                    "Checkout cleanup failed exception_type=%s",
                    type(cleanup_error).__name__,
                )
        try:
            await redis.aclose()
        except Exception as close_error:
            logger.warning("Redis close failed exception_type=%s", type(close_error).__name__)


def _selected_model_uses_oauth(model: str) -> bool:
    entry = find_model_entry(model)
    return bool(entry and entry.auth_type == "oauth")


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return str(value.get_secret_value())
    return str(value)


def _provider_key_selection_scope(state: object, settings: object) -> str:
    provider_key_scope = getattr(state, "provider_key_scope", None)
    if provider_key_scope:
        return str(provider_key_scope)
    if getattr(settings, "app_mode", None) == "hosted":
        owner_scope = getattr(state, "owner_scope", None)
        if owner_scope:
            return str(owner_scope)
        raise RuntimeError("Hosted saved provider key selection requires generation owner scope.")
    return "global"


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


def _guided_resume_prompt_context(evidence_brief: object, checkout: RepositoryCheckout) -> str:
    brief_text = (
        evidence_brief.to_prompt_context()
        if hasattr(evidence_brief, "to_prompt_context")
        else str(evidence_brief)
    )
    payload = {
        "repository": {
            "owner": checkout.owner,
            "name": checkout.name,
            "full_name": checkout.full_name,
            "canonical_url": checkout.canonical_url,
        },
        "guided_analysis": brief_text,
    }
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True)


def _author_scoped_resume_prompt_context(
    contribution_context: str, allowed_paths: set[str], checkout: RepositoryCheckout
) -> str:
    payload = {
        "repository": {
            "owner": checkout.owner,
            "name": checkout.name,
            "full_name": checkout.full_name,
            "canonical_url": checkout.canonical_url,
        },
        "contribution_scope": contribution_context,
        "analysis_policy": "Only make claims supported by files touched by the requested author.",
        "author_touched_files": sorted(allowed_paths),
    }
    if not allowed_paths:
        payload["author_touched_file_note"] = "No matching author-touched files were found."
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True)


def _guided_analysis_event_data(state: object, allowed_paths: set[str] | None) -> dict[str, object]:
    data: dict[str, object] = {"stage": "guided-evidence-investigation"}
    analysis_author = getattr(state, "analysis_author", None)
    if analysis_author:
        data["analysisAuthor"] = str(analysis_author)
        data["contributedFileCount"] = len(allowed_paths or set())
    return data


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
