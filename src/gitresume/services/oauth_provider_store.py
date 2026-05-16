import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr

from gitresume.core.crypto import StringEncryptor

SUPPORTED_OAUTH_PROVIDERS = ("github_copilot", "chatgpt")
ConnectionType = Literal["manual_token", "device_auth"]


class OAuthProviderCredentialInput(BaseModel):
    provider: str
    access_token: SecretStr = Field(exclude=True, repr=False)
    refresh_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    account_label: str | None = None
    expires_at: datetime | None = None
    connection_type: ConnectionType = "manual_token"


class OAuthTokenRefreshResult(BaseModel):
    access_token: SecretStr = Field(exclude=True, repr=False)
    refresh_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    expires_at: datetime | None = None


class OAuthTokenRefreshError(RuntimeError):
    pass


class OAuthTokenRefresher(Protocol):
    async def refresh(self, *, provider: str, refresh_token: str) -> OAuthTokenRefreshResult:
        """Refresh an OAuth access token."""


class ManualOAuthTokenRefresher:
    async def refresh(self, *, provider: str, refresh_token: str) -> OAuthTokenRefreshResult:
        del refresh_token
        raise OAuthTokenRefreshError(
            f"OAuth token for {provider} is expired; refresh or reconnect the account."
        )


class OAuthProviderAccount(BaseModel):
    id: str
    provider: str
    connection_type: ConnectionType = Field(serialization_alias="connectionType")
    account_label: str | None = Field(default=None, serialization_alias="accountLabel")
    connected_at: datetime = Field(serialization_alias="connectedAt")
    expires_at: datetime | None = Field(default=None, serialization_alias="expiresAt")
    last_refreshed_at: datetime | None = Field(default=None, serialization_alias="lastRefreshedAt")
    last_used_at: datetime | None = Field(default=None, serialization_alias="lastUsedAt")
    is_active: bool = Field(default=True, serialization_alias="isActive")
    executable: bool = True
    status: str | None = None


class OAuthProviderStatus(BaseModel):
    provider: str
    connected: bool = False
    executable: bool = True
    supports_device_code: bool = Field(default=False, serialization_alias="supportsDeviceCode")
    connection_type: ConnectionType | None = Field(
        default=None,
        serialization_alias="connectionType",
    )
    account_label: str | None = Field(default=None, serialization_alias="accountLabel")
    connected_at: datetime | None = Field(default=None, serialization_alias="connectedAt")
    accounts: list[OAuthProviderAccount] = Field(default_factory=list)
    status: str | None = None


class RedisOAuthProviderStore:
    def __init__(
        self,
        redis_client: object,
        encryptor: StringEncryptor,
        ttl_seconds: int | None = None,
        refresher: OAuthTokenRefresher | None = None,
    ) -> None:
        self.redis = redis_client
        self.encryptor = encryptor
        self.ttl_seconds = ttl_seconds
        self.refresher = refresher or ManualOAuthTokenRefresher()

    async def connect(
        self, scope: str, credential: OAuthProviderCredentialInput
    ) -> OAuthProviderStatus:
        self._validate_provider(credential.provider)
        account = await self._new_account_payload(scope, credential)
        await self._save_account(scope, credential.provider, account)
        return await self._provider_status(scope, credential.provider)

    async def update_account_token(
        self,
        scope: str,
        provider: str,
        account_id: str,
        *,
        access_token: SecretStr,
        refresh_token: SecretStr | None = None,
        expires_at: datetime | None = None,
    ) -> OAuthProviderStatus:
        self._validate_provider(provider)
        account = await self._account_payload(scope, provider, account_id)
        if account is None:
            raise KeyError("OAuth account not found.")
        account["encrypted_access_token"] = self.encryptor.encrypt(access_token.get_secret_value())
        if refresh_token is not None:
            account["encrypted_refresh_token"] = self._encrypt_optional(refresh_token)
        account["expires_at"] = self._datetime_to_str(expires_at)
        account["last_refreshed_at"] = datetime.now(UTC).isoformat()
        await self._save_account(scope, provider, account)
        return await self._provider_status(scope, provider)

    async def disconnect(self, scope: str, provider: str) -> bool:
        self._validate_provider(provider)
        legacy_deleted = await self.redis.hdel(self._providers_key(scope), provider)
        accounts_key = self._accounts_key(scope, provider)
        account_count = len(await self.redis.hgetall(accounts_key))
        if account_count:
            await self.redis.delete(accounts_key)
        return bool(legacy_deleted or account_count)

    async def disconnect_account(self, scope: str, provider: str, account_id: str) -> bool:
        self._validate_provider(provider)
        await self._migrate_legacy_provider(scope, provider)
        deleted = await self.redis.hdel(self._accounts_key(scope, provider), account_id)
        return bool(deleted)

    async def list_statuses(
        self, scope: str, providers: tuple[str, ...] = SUPPORTED_OAUTH_PROVIDERS
    ) -> list[OAuthProviderStatus]:
        return [await self._provider_status(scope, provider) for provider in providers]

    async def get_access_token(self, scope: str, provider: str) -> str | None:
        return await self.select_access_token(scope, provider)

    async def select_access_token(self, scope: str, provider: str) -> str | None:
        self._validate_provider(provider)
        await self._migrate_legacy_provider(scope, provider)
        candidates = await self._account_payloads(scope, provider)
        candidates = [
            account
            for account in candidates
            if account.get("is_active", True) and account.get("encrypted_access_token")
        ]
        if not candidates:
            return None
        counter = int(await self.redis.incr(self._rotation_key(scope, provider)))
        start_index = (counter - 1) % len(candidates)
        for offset in range(len(candidates)):
            candidate = candidates[(start_index + offset) % len(candidates)]
            account_id = str(candidate["id"])
            current = await self._account_payload(scope, provider, account_id)
            if current is None:
                continue
            if self._is_expired(current):
                refreshed = await self._try_refresh_account(scope, provider, account_id, current)
                if not refreshed:
                    continue
                current = refreshed
            encrypted_token = current.get("encrypted_access_token")
            if not encrypted_token:
                continue
            current["last_used_at"] = datetime.now(UTC).isoformat()
            await self._save_account(scope, provider, current)
            return self.encryptor.decrypt(str(encrypted_token))
        return None

    async def _try_refresh_account(
        self,
        scope: str,
        provider: str,
        account_id: str,
        account: dict[str, object],
    ) -> dict[str, object] | None:
        encrypted_refresh_token = account.get("encrypted_refresh_token")
        if not encrypted_refresh_token:
            return None
        try:
            refresh_token = self.encryptor.decrypt(str(encrypted_refresh_token))
            result = await self.refresher.refresh(provider=provider, refresh_token=refresh_token)
        except OAuthTokenRefreshError:
            return None
        current = await self._account_payload(scope, provider, account_id)
        if current is None:
            return None
        current["encrypted_access_token"] = self.encryptor.encrypt(
            result.access_token.get_secret_value()
        )
        if result.refresh_token is not None:
            current["encrypted_refresh_token"] = self.encryptor.encrypt(
                result.refresh_token.get_secret_value()
            )
        current["expires_at"] = self._datetime_to_str(result.expires_at)
        current["last_refreshed_at"] = datetime.now(UTC).isoformat()
        await self._save_account(scope, provider, current)
        return current

    async def _provider_status(self, scope: str, provider: str) -> OAuthProviderStatus:
        self._validate_provider(provider)
        await self._migrate_legacy_provider(scope, provider)
        account_payloads = await self._account_payloads(scope, provider)
        accounts = [self._account_from_payload(account) for account in account_payloads]
        connected = bool(accounts)
        executable = any(account.executable for account in accounts)
        first = accounts[0] if accounts else None
        status_text = (
            "Connected with server-stored OAuth account(s)."
            if executable
            else f"OAuth account for {provider} is expired; refresh required."
        )
        return OAuthProviderStatus(
            provider=provider,
            connected=connected,
            executable=executable,
            supports_device_code=True,
            connection_type=first.connection_type if first else None,
            account_label=first.account_label if first else None,
            connected_at=first.connected_at if first else None,
            accounts=accounts,
            status=status_text if connected else None,
        )

    async def _migrate_legacy_provider(self, scope: str, provider: str) -> None:
        raw = await self.redis.hget(self._providers_key(scope), provider)
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(str(raw))
        for account in self._normalize_legacy_accounts(payload):
            account_id = str(account["id"])
            if await self.redis.hget(self._accounts_key(scope, provider), account_id) is None:
                await self._save_account(scope, provider, account)
        await self.redis.hdel(self._providers_key(scope), provider)

    async def _account_payloads(self, scope: str, provider: str) -> list[dict[str, object]]:
        raw_items = await self.redis.hgetall(self._accounts_key(scope, provider))
        accounts = [self._decode_account(raw) for raw in raw_items.values()]
        return sorted(
            accounts,
            key=lambda account: (
                int(account.get("created_sequence") or 0),
                str(account.get("connected_at") or ""),
                str(account.get("id")),
            ),
        )

    async def _account_payload(
        self, scope: str, provider: str, account_id: str
    ) -> dict[str, object] | None:
        raw = await self.redis.hget(self._accounts_key(scope, provider), account_id)
        if raw is None:
            return None
        return self._decode_account(raw)

    async def _save_account(self, scope: str, provider: str, account: dict[str, object]) -> None:
        await self.redis.hset(
            self._accounts_key(scope, provider),
            mapping={str(account["id"]): json.dumps(account)},
        )
        if self.ttl_seconds is not None:
            await self.redis.expire(self._accounts_key(scope, provider), self.ttl_seconds)

    @staticmethod
    def _decode_account(raw: object) -> dict[str, object]:
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(str(raw))

    async def _new_account_payload(
        self, scope: str, credential: OAuthProviderCredentialInput
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        sequence = int(await self.redis.incr(self._sequence_key(scope, credential.provider)))
        return {
            "id": f"oauth-{uuid4().hex}",
            "provider": credential.provider,
            "encrypted_access_token": self.encryptor.encrypt(
                credential.access_token.get_secret_value()
            ),
            "encrypted_refresh_token": self._encrypt_optional(credential.refresh_token),
            "account_label": credential.account_label,
            "connection_type": credential.connection_type,
            "connected_at": now.isoformat(),
            "expires_at": self._datetime_to_str(credential.expires_at),
            "last_refreshed_at": None,
            "last_used_at": None,
            "is_active": True,
            "created_sequence": sequence,
        }

    def _normalize_legacy_accounts(self, payload: dict[str, object]) -> list[dict[str, object]]:
        if "accounts" in payload and isinstance(payload["accounts"], list):
            provider = str(payload["provider"])
            return [
                self._normalize_legacy_account(provider, account) for account in payload["accounts"]
            ]
        provider = str(payload["provider"])
        return [self._normalize_legacy_account(provider, payload)]

    def _normalize_legacy_account(
        self, provider: str, payload: dict[str, object]
    ) -> dict[str, object]:
        account = {
            "id": payload.get("id") or self._stable_legacy_account_id(provider, payload),
            "provider": provider,
            "encrypted_access_token": payload.get("encrypted_access_token"),
            "encrypted_refresh_token": payload.get("encrypted_refresh_token"),
            "account_label": payload.get("account_label"),
            "connection_type": payload.get("connection_type") or "manual_token",
            "connected_at": payload.get("connected_at") or datetime.now(UTC).isoformat(),
            "expires_at": payload.get("expires_at"),
            "last_refreshed_at": payload.get("last_refreshed_at"),
            "last_used_at": payload.get("last_used_at"),
            "is_active": payload.get("is_active", True),
            "created_sequence": payload.get("created_sequence", 0),
        }
        return account

    @staticmethod
    def _stable_legacy_account_id(provider: str, payload: dict[str, object]) -> str:
        stable_parts = [
            provider,
            str(payload.get("connected_at") or ""),
            str(payload.get("account_label") or ""),
            str(payload.get("encrypted_access_token") or ""),
        ]
        digest = hashlib.sha256("|".join(stable_parts).encode("utf-8")).hexdigest()[:24]
        return f"oauth-{digest}"

    @staticmethod
    def _providers_key(scope: str) -> str:
        return f"settings:{scope}:oauth-providers"

    @staticmethod
    def _accounts_key(scope: str, provider: str) -> str:
        return f"settings:{scope}:oauth-provider-accounts:{provider}"

    @staticmethod
    def _rotation_key(scope: str, provider: str) -> str:
        return f"settings:{scope}:oauth-providers:{provider}:rotation"

    @staticmethod
    def _sequence_key(scope: str, provider: str) -> str:
        return f"settings:{scope}:oauth-provider-accounts:{provider}:sequence"

    @staticmethod
    def _validate_provider(provider: str) -> None:
        if provider not in SUPPORTED_OAUTH_PROVIDERS:
            raise ValueError(f"Unsupported OAuth provider: {provider}")

    def _account_from_payload(self, payload: dict[str, object]) -> OAuthProviderAccount:
        expires_at = self._parse_datetime(payload.get("expires_at"))
        is_active = bool(payload.get("is_active", True))
        expired = expires_at is not None and expires_at <= datetime.now(UTC)
        executable = is_active and not expired
        status_text = None
        if expired:
            status_text = "OAuth token is expired; refresh required before execution."
        elif not is_active:
            status_text = "OAuth account is inactive."
        connected_at = self._parse_datetime(payload.get("connected_at")) or datetime.now(UTC)
        return OAuthProviderAccount(
            id=str(payload["id"]),
            provider=str(payload["provider"]),
            connection_type=str(payload.get("connection_type") or "manual_token"),
            account_label=(str(payload["account_label"]) if payload.get("account_label") else None),
            connected_at=connected_at,
            expires_at=expires_at,
            last_refreshed_at=self._parse_datetime(payload.get("last_refreshed_at")),
            last_used_at=self._parse_datetime(payload.get("last_used_at")),
            is_active=is_active,
            executable=executable,
            status=status_text,
        )

    @staticmethod
    def _is_expired(account: dict[str, object]) -> bool:
        expires_at = RedisOAuthProviderStore._parse_datetime(account.get("expires_at"))
        return expires_at is not None and expires_at <= datetime.now(UTC)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _datetime_to_str(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def _encrypt_optional(self, value: SecretStr | None) -> str | None:
        if value is None:
            return None
        return self.encryptor.encrypt(value.get_secret_value())


def disconnected_status(provider: str, reason: str | None = None) -> OAuthProviderStatus:
    return OAuthProviderStatus(
        provider=provider,
        connected=False,
        executable=False,
        supports_device_code=True,
        connection_type=None,
        accounts=[],
        status=reason or (f"Connect {provider} with device authorization."),
    )
