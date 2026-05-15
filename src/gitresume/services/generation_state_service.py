import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from gitresume.schemas.generation import (
    GenerationCreateRequest,
    GenerationEvent,
    GenerationState,
    GenerationStatus,
    utc_now,
)

TERMINAL_STATUSES = {GenerationStatus.SUCCEEDED, GenerationStatus.FAILED}


class RedisGenerationStateService:
    def __init__(
        self,
        redis_client: Any,
        *,
        generation_ttl_seconds: int = 86_400,
        generation_event_max_len: int = 200,
    ) -> None:
        self.redis = redis_client
        self.generation_ttl_seconds = generation_ttl_seconds
        self.generation_event_max_len = generation_event_max_len

    async def create_generation(
        self, generation_id: str, request: GenerationCreateRequest
    ) -> GenerationState:
        now = utc_now()
        state = GenerationState(
            generation_id=generation_id,
            status=GenerationStatus.QUEUED,
            repository_url=str(request.repo_url),
            job_description=request.job_description,
            model=request.model,
            provider_key_id=request.provider_key_id,
            provider_key_scope=request.provider_key_scope,
            created_at=now,
            updated_at=now,
        )
        await self.redis.hset(self._state_key(generation_id), mapping=self._state_to_hash(state))
        await self.redis.set(self._sequence_key(generation_id), 0)
        await self._refresh_generation_ttl(generation_id)
        await self.append_event(
            generation_id,
            event_type="queued",
            status=GenerationStatus.QUEUED,
            message="Generation queued",
        )
        return state

    async def append_event(
        self,
        generation_id: str,
        *,
        event_type: str,
        status: GenerationStatus | None = None,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> GenerationEvent:
        sequence = int(await self.redis.incr(self._sequence_key(generation_id)))
        event = GenerationEvent(
            generation_id=generation_id,
            event_type=event_type,
            status=status,
            message=message,
            sequence=sequence,
            data=data,
        )
        await self.redis.xadd(
            self._stream_key(generation_id),
            {"event": json.dumps(event.model_dump(mode="json"))},
            maxlen=self.generation_event_max_len,
            approximate=False,
        )
        if status is not None:
            await self.redis.hset(
                self._state_key(generation_id),
                mapping={
                    "status": status.value,
                    "updated_at": event.created_at.isoformat(),
                },
            )
        await self._refresh_generation_ttl(generation_id)
        return event

    async def set_task_id(self, generation_id: str, task_id: str) -> None:
        await self.redis.hset(
            self._state_key(generation_id),
            mapping={
                "task_id": task_id,
                "updated_at": utc_now().isoformat(),
            },
        )
        await self._refresh_generation_ttl(generation_id)

    async def complete_generation(
        self, generation_id: str, result: dict[str, Any]
    ) -> GenerationEvent:
        await self.redis.hset(
            self._state_key(generation_id),
            mapping={
                "result": json.dumps(result),
                "error": "",
            },
        )
        return await self.append_event(
            generation_id,
            event_type="completed",
            status=GenerationStatus.SUCCEEDED,
            message="Generation complete",
            data={"result": result},
        )

    async def fail_generation(self, generation_id: str, error: str) -> GenerationEvent:
        await self.redis.hset(
            self._state_key(generation_id),
            mapping={
                "error": error,
                "result": "",
            },
        )
        return await self.append_event(
            generation_id,
            event_type="failed",
            status=GenerationStatus.FAILED,
            message=error,
        )

    async def get_generation(self, generation_id: str) -> GenerationState | None:
        raw = await self.redis.hgetall(self._state_key(generation_id))
        if not raw:
            return None
        return self._state_from_hash(raw)

    async def replay_events(self, generation_id: str) -> list[GenerationEvent]:
        return [event for _, event in await self.replay_events_with_ids(generation_id)]

    async def replay_events_with_ids(
        self, generation_id: str, *, after_id: str = "0-0"
    ) -> list[tuple[str, GenerationEvent]]:
        min_id = "-" if after_id == "0-0" else f"({after_id}"
        entries = await self.redis.xrange(self._stream_key(generation_id), min=min_id, max="+")
        return [
            (str(entry_id), self._event_from_stream_fields(fields)) for entry_id, fields in entries
        ]

    async def latest_event_id(self, generation_id: str) -> str:
        entries = await self.redis.xrevrange(
            self._stream_key(generation_id), max="+", min="-", count=1
        )
        if not entries:
            return "0-0"
        entry_id, _ = entries[0]
        return str(entry_id)

    async def stream_events(
        self, generation_id: str, *, after_id: str = "0-0", block_ms: int = 1000
    ) -> AsyncIterator[GenerationEvent]:
        async for _, event in self.stream_events_with_ids(
            generation_id, after_id=after_id, block_ms=block_ms
        ):
            yield event

    async def stream_events_with_ids(
        self, generation_id: str, *, after_id: str = "0-0", block_ms: int = 1000
    ) -> AsyncIterator[tuple[str, GenerationEvent]]:
        last_id = after_id
        while True:
            response = await self.redis.xread(
                {self._stream_key(generation_id): last_id},
                count=10,
                block=block_ms,
            )
            if not response:
                state = await self.get_generation(generation_id)
                if state is not None and state.status in TERMINAL_STATUSES:
                    return
                continue

            for _, entries in response:
                for entry_id, fields in entries:
                    last_id = str(entry_id)
                    event = self._event_from_stream_fields(fields)
                    yield last_id, event
                    if event.status in TERMINAL_STATUSES:
                        return

    async def store_github_token(self, generation_id: str, token: str) -> None:
        await self.redis.set(
            self._credential_key(generation_id), token, ex=self.generation_ttl_seconds
        )

    async def store_provider_api_key(self, generation_id: str, secret: str) -> None:
        await self.redis.set(
            self._provider_api_key_key(generation_id), secret, ex=self.generation_ttl_seconds
        )

    async def pop_github_token(self, generation_id: str) -> str | None:
        key = self._credential_key(generation_id)
        token = await self.redis.getdel(key)
        if token is None:
            return None
        if isinstance(token, bytes):
            return token.decode()
        return str(token)

    async def pop_provider_api_key(self, generation_id: str) -> str | None:
        key = self._provider_api_key_key(generation_id)
        secret = await self.redis.getdel(key)
        if secret is None:
            return None
        if isinstance(secret, bytes):
            return secret.decode()
        return str(secret)

    async def delete_github_token(self, generation_id: str) -> None:
        await self.redis.delete(self._credential_key(generation_id))

    async def delete_provider_api_key(self, generation_id: str) -> None:
        await self.redis.delete(self._provider_api_key_key(generation_id))

    async def _refresh_generation_ttl(self, generation_id: str) -> None:
        ttl = self.generation_ttl_seconds
        await self.redis.expire(self._state_key(generation_id), ttl)
        await self.redis.expire(self._sequence_key(generation_id), ttl)
        await self.redis.expire(self._stream_key(generation_id), ttl)

    @staticmethod
    def _state_key(generation_id: str) -> str:
        return f"generation:{generation_id}:state"

    @staticmethod
    def _sequence_key(generation_id: str) -> str:
        return f"generation:{generation_id}:sequence"

    @staticmethod
    def _stream_key(generation_id: str) -> str:
        return f"generation:{generation_id}:events"

    @staticmethod
    def _credential_key(generation_id: str) -> str:
        return f"generation:{generation_id}:github-token"

    @staticmethod
    def _provider_api_key_key(generation_id: str) -> str:
        return f"generation:{generation_id}:provider-api-key"

    @staticmethod
    def _state_to_hash(state: GenerationState) -> dict[str, str]:
        return {
            "generation_id": state.generation_id,
            "status": state.status.value,
            "repository_url": state.repository_url,
            "job_description": state.job_description or "",
            "result": json.dumps(state.result) if state.result is not None else "",
            "error": state.error or "",
            "task_id": state.task_id or "",
            "model": state.model or "",
            "provider_key_id": state.provider_key_id or "",
            "provider_key_scope": state.provider_key_scope or "",
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

    @staticmethod
    def _state_from_hash(raw: dict[str, str]) -> GenerationState:
        result = json.loads(raw["result"]) if raw.get("result") else None
        return GenerationState(
            generation_id=raw["generation_id"],
            status=GenerationStatus(raw["status"]),
            repository_url=raw["repository_url"],
            job_description=raw.get("job_description") or None,
            result=result,
            error=raw.get("error") or None,
            task_id=raw.get("task_id") or None,
            model=raw.get("model") or None,
            provider_key_id=raw.get("provider_key_id") or None,
            provider_key_scope=raw.get("provider_key_scope") or None,
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
        )

    @staticmethod
    def _event_from_stream_fields(fields: dict[str, str]) -> GenerationEvent:
        return GenerationEvent.model_validate(json.loads(fields["event"]))
