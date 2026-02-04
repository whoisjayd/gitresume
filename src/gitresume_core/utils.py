"""
General utility functions for file and system operations.

This module provides helper functions that are used across different parts
of the application, such as robustly cleaning up directories.
"""

import logging
import os
import shutil
import stat
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _remove_readonly(func, path, exc):
    """
    Error handler for shutil.rmtree.

    This function is called when shutil.rmtree encounters an error. It changes
    the file permissions to writable and retries the deletion. This is particularly
    useful on Windows where .git files can be marked as read-only.

    Args:
        func (callable): The function that raised the exception (e.g., os.remove).
        path (str): The path to the file that caused the error.
        exc (BaseException or tuple): The exception instance (onexc) or exc_info tuple (onerror).
    """
    # Handle both onexc (exception instance) and onerror (exc_info tuple)
    exception = exc[1] if isinstance(exc, tuple) else exc

    if isinstance(exception, (PermissionError, OSError)):
        try:
            logger.debug(f"Permission error at {path}. Changing permissions and retrying.")
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception as e:
            logger.warning(f"Failed to remove {path} even after changing permissions. Error: {e}")
    else:
        # Re-raise the exception if it's not a permission error
        raise exception


def robust_rmtree(path: str, max_retries: int = 3, delay_secs: float = 1.0) -> None:
    """
    Robustly removes a directory tree, retrying on failure.

    This function attempts to remove a directory tree, handling common issues
    like read-only files (common in .git directories on Windows) and temporary
    lock files by retrying the operation.

    Args:
        path (str): The path to the directory to be removed.
        max_retries (int): The maximum number of times to retry the operation.
        delay_secs (float): The initial delay between retries, in seconds.
                            The delay increases exponentially with each retry.
    """
    path_obj = Path(path)
    if not path_obj.exists():
        logger.debug(f"Directory '{path}' does not exist, skipping cleanup.")
        return

    for attempt in range(max_retries):
        try:
            # Use onexc for Python 3.12+, fallback to onerror for older versions
            import sys

            if sys.version_info >= (3, 12):
                shutil.rmtree(path_obj, onexc=_remove_readonly)
            else:
                shutil.rmtree(path_obj, onerror=_remove_readonly)
            logger.info(f"Successfully removed directory: {path}")
            return
        except Exception as e:
            logger.warning(
                f"Failed to remove directory '{path}' on attempt {attempt + 1}/{max_retries}. "
                f"Error: {e.__class__.__name__}: {e}"
            )
            if attempt < max_retries - 1:
                sleep_time = delay_secs * (2**attempt)
                logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)

    logger.error(f"Failed to remove directory '{path}' after {max_retries} attempts.")
    # As a last resort, if the directory still exists, raise an error.
    if path_obj.exists():
        raise OSError(f"Could not remove directory: {path}")
