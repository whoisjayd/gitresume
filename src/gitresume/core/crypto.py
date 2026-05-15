import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

MIN_PASSPHRASE_LENGTH = 32


class StringEncryptor:
    """Encrypt and decrypt strings with Fernet.

    Generated Fernet keys are preferred. Passphrase mode is a compatibility
    fallback that intentionally uses SHA-256 + urlsafe base64 as required by
    the settings persistence spec.
    """

    def __init__(self, key_or_passphrase: str) -> None:
        if not key_or_passphrase:
            raise ValueError("Encryption key is required")
        self._fernet = Fernet(self._normalize_key(key_or_passphrase))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt value with the configured key") from exc

    @staticmethod
    def _normalize_key(key_or_passphrase: str) -> bytes:
        candidate = key_or_passphrase.encode("utf-8")
        try:
            Fernet(candidate)
            return candidate
        except ValueError:
            if len(key_or_passphrase) < MIN_PASSPHRASE_LENGTH:
                raise ValueError(
                    f"Encryption passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters"
                ) from None
            # Compatibility fallback: derive exactly with SHA-256 + urlsafe base64.
            # Prefer Fernet.generate_key() output for new deployments.
            digest = hashlib.sha256(candidate).digest()
            return base64.urlsafe_b64encode(digest)
