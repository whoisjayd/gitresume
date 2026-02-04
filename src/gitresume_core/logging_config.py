import logging
import re
from pathlib import Path


class RedactingFormatter(logging.Formatter):
    """Redacts sensitive information like API keys and tokens from logs."""

    # Patterns for common API keys and tokens
    PATTERNS = [
        r"(sk-[a-zA-Z0-9]{32,})",  # OpenAI
        r"(ghp_[a-zA-Z0-9]{36})",  # GitHub PAT
        r"(bearer\s+)([a-zA-Z0-9\._\-]{20,})",  # Generic Bearer token
    ]

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt, datefmt)
        self._patterns = [re.compile(p, re.IGNORECASE) for p in self.PATTERNS]

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        redacted = original
        for pattern in self._patterns:
            redacted = pattern.sub(r"\1[REDACTED]" if "(" in pattern.pattern else "[REDACTED]", redacted)
        return redacted


def setup_logging(log_file: Path | None = None, level: int = logging.INFO):
    """Sets up logging to stderr and optionally to a file."""

    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    handlers.append(console_handler)

    # File handler
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,  # Override any existing configuration
    )

    # Suppress verbose logs from third-party libraries if needed
    # logging.getLogger("httpx").setLevel(logging.WARNING)
