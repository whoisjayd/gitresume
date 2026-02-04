from unittest.mock import AsyncMock, patch

import pytest

from gitresume_core.create_resume import (
    _build_prompt,
    create_resume_tool,
    resume_to_markdown,
)


def test_resume_to_markdown():
    data = {
        "project_title": "Test Project",
        "tech_stack": ["Python", "Pytest"],
        "bullet_points": ["Improved test coverage", "Fixed bugs"],
        "future_plans": "Scale to millions",
        "interview_questions": ["How do you scale?", "What is TDD?"],
    }
    md = resume_to_markdown(data)
    assert "# Test Project" in md
    assert "Python, Pytest" in md
    assert "- Improved test coverage" in md
    assert "## Future Plans" in md
    assert "- How do you scale?" in md


def test_build_prompt():
    prompt = _build_prompt("Summary", "Tree", "Content", "Job Description")
    assert "Summary" in prompt
    assert "Tree" in prompt
    assert "Content" in prompt
    assert "Job Description" in prompt


@pytest.mark.asyncio
@patch("gitresume_core.create_resume._generate_and_parse_response", new_callable=AsyncMock)
@patch("gitresume_core.create_resume.correct_resume_grammar", new_callable=AsyncMock)
async def test_create_resume_tool(mock_grammar, mock_gen):
    mock_gen.return_value = {"project_title": "AI Project"}
    mock_grammar.return_value = {"project_title": "AI Project", "tech_stack": ["LLM"]}

    result = await create_resume_tool(
        gitingest_summary="Summary", gitingest_tree="Tree", gitingest_content="Content", generation_id="test_id"
    )

    assert result["success"] is True
    assert result["project_title"] == "AI Project"
    assert "tech_stack" in result
    mock_gen.assert_called_once()
    mock_grammar.assert_called_once()


@pytest.mark.asyncio
async def test_emit_ws_message():
    from starlette.websockets import WebSocketState

    from gitresume_core.create_resume import _emit_ws_message

    mock_ws = AsyncMock()
    mock_ws.client_state = WebSocketState.CONNECTED

    await _emit_ws_message(mock_ws, "test_type", "test_content", "gen_id")
    mock_ws.send_json.assert_called_once()


@pytest.mark.asyncio
@patch("gitresume_core.create_resume.llm_client.generate_json_completion", new_callable=AsyncMock)
async def test_generate_and_parse_response_fail(mock_json_gen):
    from gitresume_core.create_resume import _generate_and_parse_response

    mock_json_gen.side_effect = Exception("LLM Error")

    with pytest.raises(ValueError, match="AI response was not valid JSON"):
        await _generate_and_parse_response("prompt")


@pytest.mark.asyncio
@patch("gitresume_core.create_resume._generate_and_parse_response", new_callable=AsyncMock)
@patch("gitresume_core.create_resume.correct_resume_grammar", new_callable=AsyncMock)
async def test_create_resume_tool_truncation(mock_grammar, mock_gen):
    mock_gen.return_value = {"project_title": "Truncated"}
    mock_grammar.return_value = {"project_title": "Truncated"}

    long_content = "x" * 40000
    long_jd = "y" * 4000

    result = await create_resume_tool(
        gitingest_summary="Summary",
        gitingest_tree="Tree",
        gitingest_content=long_content,
        generation_id="test_trunc",
        job_description=long_jd,
    )

    assert result["success"] is True
    assert result["context_truncated"] is True

    # Check that _generate_and_parse_response was called with truncated content
    args, _ = mock_gen.call_args
    prompt = args[0]
    assert len(prompt) < 44000  # Should be truncated


@pytest.mark.asyncio
async def test_create_resume_tool_exception():
    # Test error handling in create_resume_tool
    with patch("gitresume_core.create_resume._generate_and_parse_response", side_effect=Exception("Critical")):
        result = await create_resume_tool("s", "t", "c", "gen_err")
        assert result["success"] is False
        assert "Critical" in result["error"]
