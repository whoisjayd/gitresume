from pydantic import BaseModel, ConfigDict, Field, SecretStr

from gitresume.services.settings_store import RedisSettingsStore, StoredProviderKey


class ProviderKeySelectionError(ValueError):
    pass


class SelectedProviderKey(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    metadata: StoredProviderKey
    secret: SecretStr = Field(exclude=True)


class RedisProviderKeySelector:
    def __init__(self, redis_client: object, settings_store: RedisSettingsStore) -> None:
        self.redis = redis_client
        self.settings_store = settings_store

    async def select(
        self,
        *,
        scope: str,
        provider: str,
        model: str | None = None,
        provider_key_id: str | None = None,
    ) -> SelectedProviderKey | None:
        if provider_key_id is not None:
            return await self._select_explicit(scope, provider, model, provider_key_id)

        candidates = [
            key
            for key in await self.settings_store.list_provider_keys(scope)
            if self._is_compatible(key, provider, model)
        ]
        if not candidates:
            return None
        counter = int(await self.redis.incr(self._rotation_key(scope, provider, model)))
        start_index = (counter - 1) % len(candidates)
        for offset in range(len(candidates)):
            selected = candidates[(start_index + offset) % len(candidates)]
            try:
                return await self._with_secret(scope, selected)
            except ProviderKeySelectionError:
                continue
        raise ProviderKeySelectionError("No compatible provider key secret is available.")

    async def _select_explicit(
        self, scope: str, provider: str, model: str | None, provider_key_id: str
    ) -> SelectedProviderKey:
        key = await self.settings_store.get_provider_key(scope, provider_key_id)
        if key is None:
            raise ProviderKeySelectionError("Provider key not found.")
        if not key.is_active:
            raise ProviderKeySelectionError("Provider key is not active.")
        if key.provider != provider:
            raise ProviderKeySelectionError("Provider key is not compatible with provider.")
        if key.model is not None and key.model != model:
            raise ProviderKeySelectionError("Provider key is not compatible with model.")
        return await self._with_secret(scope, key)

    async def _with_secret(self, scope: str, key: StoredProviderKey) -> SelectedProviderKey:
        secret = await self.settings_store.get_provider_secret(scope, key.id)
        if secret is None:
            raise ProviderKeySelectionError("Provider key secret is unavailable.")
        return SelectedProviderKey(metadata=key, secret=SecretStr(secret))

    @staticmethod
    def _is_compatible(key: StoredProviderKey, provider: str, model: str | None) -> bool:
        return (
            key.is_active and key.provider == provider and (key.model is None or key.model == model)
        )

    @staticmethod
    def _rotation_key(scope: str, provider: str, model: str | None) -> str:
        model_part = model or "default"
        return f"settings:{scope}:provider-keys:{provider}:{model_part}:rotation"
