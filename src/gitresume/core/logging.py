import logging

from gitresume.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure process-wide logging once for the API server."""

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
