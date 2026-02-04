import logging
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Shuts down logging to release file handles after each test."""
    yield
    logging.shutdown()
    # Also explicitly remove handlers from root logger
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        handler.close()

def on_rmtree_error(func, path, exc):
    """Error handler for shutil.rmtree to handle read-only files on Windows."""
    import os
    import stat
    # Handle both onexc (exception instance) and onerror (exc_info tuple)
    exception = exc[1] if isinstance(exc, tuple) else exc

    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise exception

@pytest.fixture
def temp_artifact_dir():
    """Provides a temporary directory for artifacts."""
    tmp_dir = tempfile.mkdtemp()
    yield Path(tmp_dir)
    # Ensure all logging is shut down before rmtree
    logging.shutdown()
    try:
        shutil.rmtree(tmp_dir, onexc=on_rmtree_error)
    except Exception:
        # On Windows sometimes files are still locked even after shutdown
        import time
        time.sleep(0.5)
        shutil.rmtree(tmp_dir, ignore_errors=True)

@pytest.fixture
def mock_llm():
    """Provides a mocked LLM client."""
    mock = MagicMock()
    # Configure default mock behavior here if needed
    return mock
