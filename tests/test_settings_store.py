import json

import pytest
from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from pydantic import ValidationError

SETTINGS_KEY = "settings encryption passphrase with enough entropy"


def test_settings_allows_saved_byok_without_encryption_key_for_disabled_runtime_status() -> None:
    from gitresume.core.config import Settings

    settings = Settings(allow_saved_byok=True, settings_encryption_key=None)

    assert settings.allow_saved_byok is True
    assert settings.settings_encryption_key is None


def test_settings_defaults_to_self_hosted_app_mode() -> None:
    from gitresume.core.config import Settings

    assert Settings().app_mode == "self_hosted"


def test_settings_accepts_hosted_app_mode() -> None:
    from gitresume.core.config import Settings

    assert Settings(app_mode="hosted").app_mode == "hosted"


def test_settings_rejects_invalid_app_mode() -> None:
    from gitresume.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(app_mode="invalid")


def test_settings_accepts_saved_byok_with_long_encryption_key() -> None:
    from gitresume.core.config import Settings

    settings = Settings(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    assert settings.allow_saved_byok is True


def test_settings_encryption_key_does_not_leak_in_repr_or_json() -> None:
    from gitresume.core.config import Settings

    settings = Settings(allow_saved_byok=True, settings_encryption_key=SETTINGS_KEY)

    assert SETTINGS_KEY not in repr(settings)
    assert SETTINGS_KEY not in settings.model_dump_json()


def test_settings_rejects_saved_byok_with_short_encryption_key() -> None:
    from gitresume.core.config import Settings

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(allow_saved_byok=True, settings_encryption_key="too-short")


def test_encryptor_round_trips_and_wrong_key_fails() -> None:
    from gitresume.core.crypto import StringEncryptor

    encryptor = StringEncryptor("a long passphrase for local dashboard settings")
    wrong_encryptor = StringEncryptor("a different long passphrase for settings")

    token = encryptor.encrypt("provider-secret")

    assert token != "provider-secret"
    assert encryptor.decrypt(token) == "provider-secret"
    with pytest.raises(ValueError, match="decrypt"):
        wrong_encryptor.decrypt(token)


def test_encryptor_accepts_valid_fernet_key_input() -> None:
    from gitresume.core.crypto import StringEncryptor

    encryptor = StringEncryptor(Fernet.generate_key().decode("utf-8"))

    token = encryptor.encrypt("provider-secret")

    assert encryptor.decrypt(token) == "provider-secret"


def test_encryptor_rejects_short_passphrase() -> None:
    from gitresume.core.crypto import StringEncryptor

    with pytest.raises(ValueError, match="at least 32 characters"):
        StringEncryptor("short-passphrase")


def test_provider_key_input_secret_does_not_leak_in_repr_or_json() -> None:
    from gitresume.services.settings_store import ProviderKeyInput

    key_input = ProviderKeyInput(provider="openai", label="OpenAI", secret="raw-secret")

    assert "raw-secret" not in repr(key_input)
    assert "raw-secret" not in key_input.model_dump_json()


@pytest.mark.asyncio
async def test_settings_store_lists_metadata_without_secret_leakage() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))

    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(
            provider="openai",
            label="Work key",
            secret="sk-super-secret",
            model="openai/gpt-4o-mini",
        ),
    )

    listed = await store.list_provider_keys("global")
    raw = await redis.hgetall("settings:global:provider-keys")

    assert listed == [saved]
    assert not hasattr(listed[0], "secret")
    assert "sk-super-secret" not in listed[0].model_dump_json()
    assert "sk-super-secret" not in str(raw)


@pytest.mark.asyncio
async def test_settings_store_decrypts_secret_by_id() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    saved = await store.save_provider_key(
        "user:123",
        ProviderKeyInput(provider="gemini", label="Gemini", secret="gemini-secret"),
    )

    assert await store.get_provider_secret("user:123", saved.id) == "gemini-secret"
    assert await store.get_provider_secret("user:123", "missing") is None


@pytest.mark.asyncio
async def test_settings_store_supports_default_byte_responses() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis()
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(
            provider="openai",
            label="OpenAI",
            secret="byte-secret",
            model="openai/gpt-4o-mini",
        ),
    )
    await store.set_default_model("global", "openai/gpt-4o-mini")

    listed = await store.list_provider_keys("global")
    secret = await store.get_provider_secret("global", saved.id)
    dashboard_settings = await store.get_dashboard_settings("global")

    assert listed == [saved]
    assert secret == "byte-secret"
    assert dashboard_settings.default_model == "openai/gpt-4o-mini"
    assert dashboard_settings.provider_keys == [saved]


@pytest.mark.asyncio
async def test_settings_store_get_provider_key_returns_metadata_without_secret() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(provider="openai", label="OpenAI", secret="metadata-secret"),
    )

    loaded = await store.get_provider_key("global", saved.id)

    assert loaded == saved
    assert loaded is not None
    assert not hasattr(loaded, "secret")
    assert "metadata-secret" not in loaded.model_dump_json()


@pytest.mark.asyncio
async def test_settings_store_get_provider_key_missing_id_returns_none() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))

    assert await store.get_provider_key("global", "missing") is None


@pytest.mark.asyncio
async def test_delete_provider_key_removes_key_and_secret() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(provider="anthropic", label="Claude", secret="anthropic-secret"),
    )

    assert await store.delete_provider_key("global", saved.id) is True
    assert await store.delete_provider_key("global", saved.id) is False
    assert await store.list_provider_keys("global") == []
    assert await store.get_provider_secret("global", saved.id) is None


@pytest.mark.asyncio
async def test_settings_store_applies_ttl_to_keys_after_mutations() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY), ttl_seconds=60)
    saved = await store.save_provider_key(
        "global",
        ProviderKeyInput(provider="openai", label="OpenAI", secret="ttl-secret"),
    )
    provider_key = "settings:global:provider-keys"
    dashboard_key = "settings:global:dashboard"

    assert await redis.ttl(provider_key) > 0
    assert await redis.ttl(dashboard_key) > 0

    await store.set_default_model("global", "openai/gpt-4o-mini")

    assert await redis.ttl(provider_key) > 0
    assert await redis.ttl(dashboard_key) > 0

    await store.delete_provider_key("global", saved.id)

    assert await redis.ttl(provider_key) > 0
    assert await redis.ttl(dashboard_key) > 0


@pytest.mark.asyncio
async def test_dashboard_default_model_persists() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))

    updated = await store.set_default_model("global", "openai/gpt-4o-mini")
    loaded = await store.get_dashboard_settings("global")
    cleared = await store.set_default_model("global", None)

    assert updated.default_model == "openai/gpt-4o-mini"
    assert loaded.default_model == "openai/gpt-4o-mini"
    assert cleared.default_model is None


@pytest.mark.asyncio
async def test_dashboard_settings_include_provider_metadata_without_secrets() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import ProviderKeyInput, RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))

    saved = await store.save_provider_key(
        "user:123",
        ProviderKeyInput(provider="openai", label="OpenAI", secret="secret-value"),
    )

    settings = await store.get_dashboard_settings("user:123")

    assert settings.provider_keys == [saved]
    assert "secret-value" not in settings.model_dump_json()


@pytest.mark.asyncio
async def test_provider_key_list_order_is_stable_by_created_at_then_id() -> None:
    from gitresume.core.crypto import StringEncryptor
    from gitresume.services.settings_store import RedisSettingsStore

    redis = FakeRedis(decode_responses=True)
    store = RedisSettingsStore(redis, StringEncryptor(SETTINGS_KEY))
    raw_items = {
        "key-b": {
            "id": "key-b",
            "provider": "openai",
            "label": "Second by id",
            "model": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used_at": None,
            "is_active": True,
            "encrypted_secret": "not-returned",
        },
        "key-a": {
            "id": "key-a",
            "provider": "gemini",
            "label": "First by id",
            "model": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used_at": None,
            "is_active": True,
            "encrypted_secret": "not-returned",
        },
        "key-c": {
            "id": "key-c",
            "provider": "anthropic",
            "label": "Later by time",
            "model": None,
            "created_at": "2026-01-02T00:00:00+00:00",
            "last_used_at": None,
            "is_active": True,
            "encrypted_secret": "not-returned",
        },
    }
    await redis.hset(
        "settings:global:provider-keys",
        mapping={key: json.dumps(value) for key, value in raw_items.items()},
    )

    listed = await store.list_provider_keys("global")

    assert [key.id for key in listed] == ["key-a", "key-b", "key-c"]
