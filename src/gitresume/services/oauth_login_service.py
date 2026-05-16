from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from gitresume.core.config import Settings
from gitresume.services.oauth_provider_store import (
    OAuthProviderCredentialInput,
    RedisOAuthProviderStore,
)

OAUTH_LOGIN_JOB_TTL_SECONDS = 30 * 60
OAUTH_LOGIN_TIMEOUT_SECONDS = 15 * 60
DEVICE_CODE_PATTERN = re.compile(
    r"(?i)(?:user[_ -]?code|device[_ -]?code|code)[:\s]+([A-Z0-9][A-Z0-9\-]{3,})"
)
URL_PATTERN = re.compile(r"https?://[^\s)>'\"]+")

SAFE_LOGIN_MODELS = {
    "chatgpt": ("chatgpt/gpt-5.2", "responses"),
    "github_copilot": ("github_copilot/gpt-5-mini", "chat"),
}


class OAuthLoginJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    provider: str
    status: str
    status_url: str = Field(alias="statusUrl")
    message: str
    verification_uri: str | None = Field(default=None, alias="verificationUri")
    user_code: str | None = Field(default=None, alias="userCode")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OAuthLoginService:
    def __init__(
        self,
        redis_client: object,
        settings: Settings,
        store: RedisOAuthProviderStore,
        scope: str,
    ) -> None:
        self.redis = redis_client
        self.settings = settings
        self.store = store
        self.scope = scope

    async def start(self, provider: str) -> OAuthLoginJob:
        if provider not in SAFE_LOGIN_MODELS:
            raise ValueError("Unsupported OAuth provider.")
        job = OAuthLoginJob(
            job_id=f"oauth-login-{uuid4().hex}",
            provider=provider,
            status="queued",
            status_url="",
            message="OAuth device authorization queued.",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        job.status_url = f"/api/oauth-providers/login-jobs/{job.job_id}"
        await self.save_job(job)
        asyncio.create_task(self.run(job.job_id))
        return job

    async def get(self, job_id: str) -> OAuthLoginJob | None:
        raw = await self.redis.get(self._key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return OAuthLoginJob.model_validate_json(str(raw))

    async def save_job(self, job: OAuthLoginJob) -> None:
        await self.redis.set(
            self._key(job.job_id),
            job.model_dump_json(by_alias=True),
            ex=OAUTH_LOGIN_JOB_TTL_SECONDS,
        )

    async def run(self, job_id: str) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        try:
            job.status = "running"
            job.message = "Starting LiteLLM device authorization."
            job.updated_at = datetime.now(UTC)
            await self.save_job(job)

            stdout, stderr, return_code = await self._run_litellm_login(job)
            sanitized = sanitize_oauth_output("\n".join(part for part in [stdout, stderr] if part))
            parsed = parse_device_auth_output(sanitized)
            job.verification_uri = parsed.get("verification_uri")
            job.user_code = parsed.get("user_code")
            if job.verification_uri or job.user_code:
                job.status = "code_pending"
                job.message = (
                    "Complete device authorization in your browser, then wait for this "
                    "job to finish."
                )
                job.updated_at = datetime.now(UTC)
                await self.save_job(job)

            if return_code != 0:
                raise RuntimeError(
                    "LiteLLM OAuth login failed. Check the device authorization output "
                    "and try again."
                )

            credential = load_litellm_oauth_credential(
                job.provider, self.settings.litellm_oauth_token_root
            )
            await self.store.connect(self.scope, credential)
            job.status = "succeeded"
            job.message = f"Connected {job.provider} with device authorization."
            job.updated_at = datetime.now(UTC)
            await self.save_job(job)
        except Exception as error:
            job.status = "failed"
            job.message = sanitize_oauth_output(str(error)) or "OAuth login failed."
            job.updated_at = datetime.now(UTC)
            await self.save_job(job)

    async def _run_litellm_login(self, job: OAuthLoginJob) -> tuple[str, str, int]:
        model, mode = SAFE_LOGIN_MODELS[job.provider]
        token_root = self.settings.litellm_oauth_token_root
        token_root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["CHATGPT_TOKEN_DIR"] = str(token_root / "chatgpt")
        env["GITHUB_COPILOT_TOKEN_DIR"] = str(token_root / "github_copilot")
        script = _login_script(model, mode)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            await asyncio.wait_for(
                self._collect_litellm_process_output(
                    process,
                    job.job_id,
                    stdout_parts,
                    stderr_parts,
                ),
                timeout=OAUTH_LOGIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("LiteLLM OAuth login timed out. Try connecting again.") from None
        return "".join(stdout_parts), "".join(stderr_parts), int(process.returncode or 0)

    async def _collect_litellm_process_output(
        self,
        process: asyncio.subprocess.Process,
        job_id: str,
        stdout_parts: list[str],
        stderr_parts: list[str],
    ) -> None:
        await asyncio.gather(
            self._collect_stream_output(process.stdout, job_id, stdout_parts),
            self._collect_stream_output(process.stderr, job_id, stderr_parts),
        )
        await process.wait()

    async def _collect_stream_output(
        self,
        stream: asyncio.StreamReader | None,
        job_id: str,
        output_parts: list[str],
    ) -> None:
        if stream is None:
            return
        while chunk := await stream.readline():
            output_parts.append(chunk.decode(errors="replace"))
            await self._save_device_code_from_output(job_id, "".join(output_parts))

    async def _save_device_code_from_output(self, job_id: str, output: str) -> None:
        parsed = parse_device_auth_output(sanitize_oauth_output(output))
        if not parsed.get("verification_uri") and not parsed.get("user_code"):
            return
        job = await self.get(job_id)
        if job is None or job.status in {"succeeded", "failed"}:
            return
        job.verification_uri = parsed.get("verification_uri") or job.verification_uri
        job.user_code = parsed.get("user_code") or job.user_code
        job.status = "code_pending"
        job.message = (
            "Complete device authorization in your browser, then wait for this job to finish."
        )
        job.updated_at = datetime.now(UTC)
        await self.save_job(job)

    @staticmethod
    def _key(job_id: str) -> str:
        return f"oauth-login:{job_id}"


def _login_script(model: str, mode: str) -> str:
    if mode == "responses":
        return f"""
import asyncio
import litellm
async def main():
    await litellm.aresponses(
        model={model!r},
        instructions='Validate OAuth login for GitResume.',
        input=[{{'role':'user','content':'Return ok.'}}],
        max_output_tokens=8,
    )
asyncio.run(main())
"""
    return f"""
import asyncio
from litellm import acompletion
async def main():
    await acompletion(
        model={model!r},
        messages=[
            {{'role':'system','content':'Validate OAuth login for GitResume.'}},
            {{'role':'user','content':'Return ok.'}},
        ],
        max_tokens=8,
    )
asyncio.run(main())
"""


def parse_device_auth_output(output: str) -> dict[str, str]:
    urls = URL_PATTERN.findall(output)
    code_match = DEVICE_CODE_PATTERN.search(output)
    return {
        "verification_uri": urls[0] if urls else "",
        "user_code": code_match.group(1) if code_match else "",
    }


def sanitize_oauth_output(output: str) -> str:
    sanitized = re.sub(
        r"(?i)(access_token|refresh_token|id_token|token)\s*[:=]\s*[^\s,}]+",
        r"\1=<redacted>",
        output,
    )
    sanitized = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+", r"\1<redacted>", sanitized)
    return sanitized.strip()


def load_litellm_oauth_credential(provider: str, token_root: Path) -> OAuthProviderCredentialInput:
    if provider == "chatgpt":
        return _load_chatgpt_credential(token_root / "chatgpt" / "auth.json")
    if provider == "github_copilot":
        return _load_copilot_credential(token_root / "github_copilot" / "api-key.json")
    raise ValueError("Unsupported OAuth provider.")


def _load_chatgpt_credential(path: Path) -> OAuthProviderCredentialInput:
    payload = _read_json(path)
    access_token = _required_string(payload, "access_token", path)
    refresh_token = _optional_string(payload, "refresh_token")
    account_id = _optional_string(payload, "account_id")
    return OAuthProviderCredentialInput(
        provider="chatgpt",
        access_token=SecretStr(access_token),
        refresh_token=SecretStr(refresh_token) if refresh_token else None,
        expires_at=_expires_at(payload.get("expires_at")),
        account_label=account_id or "ChatGPT device login",
        connection_type="device_auth",
    )


def _load_copilot_credential(path: Path) -> OAuthProviderCredentialInput:
    payload = _read_json(path)
    token = _required_string(payload, "token", path)
    label = _optional_string(payload, "tracking_id") or _optional_string(payload, "sku")
    return OAuthProviderCredentialInput(
        provider="github_copilot",
        access_token=SecretStr(token),
        expires_at=_expires_at(payload.get("expires_at")),
        account_label=label or "GitHub Copilot device login",
        connection_type="device_auth",
    )


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"LiteLLM OAuth token file was not created: {path.name}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"LiteLLM OAuth token file is not valid JSON: {path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"LiteLLM OAuth token file has an unsupported shape: {path.name}")
    return payload


def _required_string(payload: dict[str, object], key: str, path: Path) -> str:
    value = _optional_string(payload, key)
    if not value:
        raise ValueError(f"LiteLLM OAuth token file is missing {key}: {path.name}")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _expires_at(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    try:
        return datetime.fromtimestamp(float(str(value)), tz=UTC)
    except ValueError:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
