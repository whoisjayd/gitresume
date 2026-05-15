import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr

from gitresume.core.crypto import StringEncryptor

INTERNAL_FIELD = "_settings"


class ProviderKeyInput(BaseModel):
    provider: str
    label: str
    secret: SecretStr
    model: str | None = None


class StoredProviderKey(BaseModel):
    id: str
    provider: str
    label: str
    model: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    is_active: bool = True


class DashboardSettings(BaseModel):
    default_model: str | None = None
    provider_keys: list[StoredProviderKey] = Field(default_factory=list)


class RedisSettingsStore:
    def __init__(
        self,
        redis_client: Any,
        encryptor: StringEncryptor,
        ttl_seconds: int | None = None,
    ) -> None:
        self.redis = redis_client
        self.encryptor = encryptor
        self.ttl_seconds = ttl_seconds

    async def save_provider_key(self, scope: str, key_input: ProviderKeyInput) -> StoredProviderKey:
        stored = StoredProviderKey(
            id=uuid4().hex,
            provider=key_input.provider,
            label=key_input.label,
            model=key_input.model,
            created_at=datetime.now(UTC),
        )
        payload = stored.model_dump(mode="json") | {
            "encrypted_secret": self.encryptor.encrypt(key_input.secret.get_secret_value())
        }
        await self._hset_with_ttl(
            scope,
            self._provider_keys_key(scope),
            {stored.id: json.dumps(payload)},
            touch_dashboard=True,
        )
        return stored

    async def get_dashboard_settings(self, scope: str) -> DashboardSettings:
        return DashboardSettings(
            default_model=await self._get_default_model(scope),
            provider_keys=await self.list_provider_keys(scope),
        )

    async def set_default_model(self, scope: str, model: str | None) -> DashboardSettings:
        settings_key = self._dashboard_settings_key(scope)
        if model is None:
            await self._hdel_with_ttl(scope, settings_key, "default_model", touch_dashboard=True)
        else:
            await self._hset_with_ttl(
                scope, settings_key, {"default_model": model}, touch_dashboard=True
            )
        return await self.get_dashboard_settings(scope)

    async def list_provider_keys(self, scope: str) -> list[StoredProviderKey]:
        raw_items = await self.redis.hgetall(self._provider_keys_key(scope))
        keys = [
            self._stored_key_from_payload(json.loads(value))
            for field, value in raw_items.items()
            if not self._is_internal_field(field)
        ]
        return sorted(keys, key=lambda key: (key.created_at, key.id))

    async def get_provider_key(self, scope: str, key_id: str) -> StoredProviderKey | None:
        raw = await self.redis.hget(self._provider_keys_key(scope), key_id)
        if raw is None:
            return None
        return self._stored_key_from_payload(json.loads(raw))

    async def get_provider_secret(self, scope: str, key_id: str) -> str | None:
        raw = await self.redis.hget(self._provider_keys_key(scope), key_id)
        if raw is None:
            return None
        payload = json.loads(raw)
        encrypted_secret = payload.get("encrypted_secret")
        if not encrypted_secret:
            return None
        return self.encryptor.decrypt(encrypted_secret)

    async def delete_provider_key(self, scope: str, key_id: str) -> bool:
        deleted = await self._hdel_with_ttl(
            scope, self._provider_keys_key(scope), key_id, touch_dashboard=True
        )
        return bool(deleted)

    async def _hset_with_ttl(
        self,
        scope: str,
        key: str,
        mapping: dict[str, str],
        *,
        touch_dashboard: bool = False,
    ) -> None:
        if self.ttl_seconds is None:
            await self.redis.hset(key, mapping=mapping)
            return

        dashboard_key = self._dashboard_settings_key(scope)
        provider_keys_key = self._provider_keys_key(scope)
        pipe = self.redis.pipeline(transaction=True)
        pipe.hset(key, mapping=mapping)
        if touch_dashboard:
            pipe.hset(provider_keys_key, mapping={INTERNAL_FIELD: "1"})
            pipe.hset(dashboard_key, mapping={INTERNAL_FIELD: "1"})
        pipe.expire(provider_keys_key, self.ttl_seconds)
        pipe.expire(dashboard_key, self.ttl_seconds)
        await pipe.execute()

    async def _hdel_with_ttl(
        self,
        scope: str,
        key: str,
        field: str,
        *,
        touch_dashboard: bool = False,
    ) -> int:
        if self.ttl_seconds is None:
            return int(await self.redis.hdel(key, field))

        dashboard_key = self._dashboard_settings_key(scope)
        provider_keys_key = self._provider_keys_key(scope)
        pipe = self.redis.pipeline(transaction=True)
        pipe.hdel(key, field)
        if touch_dashboard:
            pipe.hset(provider_keys_key, mapping={INTERNAL_FIELD: "1"})
            pipe.hset(dashboard_key, mapping={INTERNAL_FIELD: "1"})
        pipe.expire(provider_keys_key, self.ttl_seconds)
        pipe.expire(dashboard_key, self.ttl_seconds)
        results = await pipe.execute()
        return int(results[0])

    async def _get_default_model(self, scope: str) -> str | None:
        model = await self.redis.hget(self._dashboard_settings_key(scope), "default_model")
        if model is None:
            return None
        if isinstance(model, bytes):
            return model.decode()
        return str(model)

    @staticmethod
    def _provider_keys_key(scope: str) -> str:
        return f"settings:{scope}:provider-keys"

    @staticmethod
    def _dashboard_settings_key(scope: str) -> str:
        return f"settings:{scope}:dashboard"

    @staticmethod
    def _stored_key_from_payload(payload: dict[str, Any]) -> StoredProviderKey:
        return StoredProviderKey.model_validate(
            {key: value for key, value in payload.items() if key != "encrypted_secret"}
        )

    @staticmethod
    def _is_internal_field(field: str | bytes) -> bool:
        if isinstance(field, bytes):
            return field.decode() == INTERNAL_FIELD
        return field == INTERNAL_FIELD
