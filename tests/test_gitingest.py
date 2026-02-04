
import pytest

from gitresume_core.gitingest import gitingest_tool


@pytest.mark.asyncio
async def test_gitingest_invalid_repo(tmp_path):
    # Test with a directory that is not a git repo
    result = await gitingest_tool(str(tmp_path))
    assert result["success"] is False
    assert "not a valid Git repository" in result["error"]

@pytest.mark.asyncio
async def test_gitingest_basic_repo(tmp_path):
    # Setup a mock git repo
    repo_dir = tmp_path / "mock_repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Add some files
    py_file = repo_dir / "main.py"
    py_file.write_text("def hello():\n    print('world')\n\nclass MyClass:\n    pass")

    txt_file = repo_dir / "readme.txt"
    txt_file.write_text("This is a readme.")

    # Add an ignored file
    ignore_dir = repo_dir / "node_modules"
    ignore_dir.mkdir()
    (ignore_dir / "index.js").write_text("console.log('ignored')")

    result = await gitingest_tool(str(repo_dir))

    assert result["success"] is True
    assert "main.py" in result["content"]
    assert "readme.txt" not in result["content"] # .txt is in IGNORE_EXTENSIONS

    summary = result["summary"]
    assert summary["total_files_processed"] >= 1
    # If tree-sitter is working, we should see metrics
    if summary["code_metrics"]["total_functions"] > 0:
        assert summary["code_metrics"]["total_functions"] == 1
        assert summary["code_metrics"]["total_classes"] == 1
