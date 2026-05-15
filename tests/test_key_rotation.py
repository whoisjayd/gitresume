import json
from datetime import UTC, datetime

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr

from gitresume.core.crypto import StringEncryptor
from gitresume.services.settings_store import (
    ProviderKeyInput,
    RedisSettingsStore,
    StoredProviderKey,
)

SETTINGS_KEY = "settings encryption passphrase with enough entropy"


@pytest.mark.asyncio
async def test_key_rotation_selects_active_matching_keys_round_robin() -> None:
    from gitresume.services.key_rotation import RedisProviderKeySelector

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    first = await store.save_provider_key(
        "global", ProviderKeyInput(provider="openai", label="First", secret="first-secret")
    )
    second = await store.save_provider_key(
        "global", ProviderKeyInput(provider="openai", label="Second", secret="second-secret")
    )
    await store.save_provider_key(
        "global", ProviderKeyInput(provider="anthropic", label="Other", secret="other-secret")
    )

    selector = RedisProviderKeySelector(redis, store)

    selected = [
        await selector.select(scope="global", provider="openai"),
        await selector.select(scope="global", provider="openai"),
        await selector.select(scope="global", provider="openai"),
    ]

    assert [item.metadata.id for item in selected] == [first.id, second.id, first.id]
    assert [item.secret.get_secret_value() for item in selected] == [
        "first-secret",
        "second-secret",
        "first-secret",
    ]


@pytest.mark.asyncio
async def test_key_rotation_respects_model_specific_keys_and_provider_key_id() -> None:
    from gitresume.services.key_rotation import RedisProviderKeySelector

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    generic = await store.save_provider_key(
        "global", ProviderKeyInput(provider="openai", label="Generic", secret="generic-secret")
    )
    specific = await store.save_provider_key(
        "global",
        ProviderKeyInput(
            provider="openai",
            label="Specific",
            secret="specific-secret",
            model="openai/gpt-4o-mini",
        ),
    )

    selector = RedisProviderKeySelector(redis, store)

    model_match = await selector.select(
        scope="global", provider="openai", model="openai/gpt-4o-mini"
    )
    explicit = await selector.select(
        scope="global",
        provider="openai",
        model="openai/gpt-4o-mini",
        provider_key_id=specific.id,
    )

    assert model_match.metadata.id == generic.id
    assert explicit.metadata.id == specific.id
    assert explicit.secret.get_secret_value() == "specific-secret"


@pytest.mark.asyncio
async def test_key_rotation_rejects_inactive_or_incompatible_explicit_key() -> None:
    from gitresume.services.key_rotation import ProviderKeySelectionError, RedisProviderKeySelector

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(
            provider="openai",
            label="OpenAI",
            secret="inactive-secret",
            model="openai/gpt-4o-mini",
        ),
    )
    raw = json.loads(await redis.hget("settings:global:provider-keys", saved.id))
    raw["is_active"] = False
    await redis.hset("settings:global:provider-keys", saved.id, json.dumps(raw))

    selector = RedisProviderKeySelector(redis, store)

    with pytest.raises(ProviderKeySelectionError, match="active"):
        await selector.select(
            scope="global",
            provider="openai",
            model="openai/gpt-4o-mini",
            provider_key_id=saved.id,
        )


@pytest.mark.asyncio
async def test_selected_provider_key_secret_does_not_leak_in_repr_or_dump() -> None:
    from gitresume.services.key_rotation import SelectedProviderKey

    selected = SelectedProviderKey(
        metadata=StoredProviderKey(
            id="key-1",
            provider="openai",
            label="OpenAI",
            created_at=datetime.now(UTC),
        ),
        secret=SecretStr("super-secret"),
    )

    assert "super-secret" not in repr(selected)
    assert "super-secret" not in selected.model_dump_json()


@pytest.mark.asyncio
async def test_key_rotation_falls_back_when_initial_candidate_secret_missing() -> None:
    from gitresume.services.key_rotation import RedisProviderKeySelector

    class FakeRedisCounter:
        async def incr(self, key: str) -> int:
            del key
            return 1

    class FakeStore:
        first = StoredProviderKey(
            id="first",
            provider="openai",
            label="First",
            created_at=datetime.now(UTC),
        )
        second = StoredProviderKey(
            id="second",
            provider="openai",
            label="Second",
            created_at=datetime.now(UTC),
        )

        async def list_provider_keys(self, scope: str) -> list[StoredProviderKey]:
            assert scope == "global"
            return [self.first, self.second]

        async def get_provider_secret(self, scope: str, key_id: str) -> str | None:
            assert scope == "global"
            return None if key_id == "first" else "second-secret"

    selected = await RedisProviderKeySelector(FakeRedisCounter(), FakeStore()).select(
        scope="global", provider="openai"
    )

    assert selected is not None
    assert selected.metadata.id == "second"
    assert selected.secret.get_secret_value() == "second-secret"
