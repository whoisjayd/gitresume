import pytest
import os
import stat
from pathlib import Path
from gitresume_core.utils import robust_rmtree

def test_robust_rmtree_nonexistent():
    # Should not raise error
    robust_rmtree("nonexistent_path_12345")

def test_robust_rmtree_basic(tmp_path):
    d = tmp_path / "test_dir"
    d.mkdir()
    f = d / "file.txt"
    f.write_text("hello")

    assert d.exists()
    robust_rmtree(str(d))
    assert not d.exists()

def test_robust_rmtree_readonly(tmp_path):
    d = tmp_path / "test_dir_readonly"
    d.mkdir()
    f = d / "readonly.txt"
    f.write_text("cannot delete me easily")

    # Make file read-only
    mode = os.stat(f).st_mode
    os.chmod(f, mode & ~stat.S_IWRITE)

    # On Windows, rmtree often fails on read-only files without onerror
    robust_rmtree(str(d))
    assert not d.exists()

def test_robust_rmtree_retry(tmp_path):
    # This is harder to test without mocking os.remove to fail once
    d = tmp_path / "test_retry"
    d.mkdir()
    (d / "file.txt").write_text("test")

    with patch("shutil.rmtree") as mock_rmtree:
        mock_rmtree.side_effect = [Exception("Locked"), None]
        with patch("time.sleep"): # Don't actually sleep
            robust_rmtree(str(d), max_retries=2, delay_secs=0.01)
            assert mock_rmtree.call_count == 2

from unittest.mock import patch
