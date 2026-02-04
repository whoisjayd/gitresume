import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from gitresume_core.llm import UnifiedLLMClient

@pytest.mark.asyncio
@patch("litellm.acompletion")
async def test_generate_completion(mock_acompletion):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test completion"
    mock_acompletion.return_value = mock_response

    client = UnifiedLLMClient(default_model="test-model")
    result = await client.generate_completion(messages=[{"role": "user", "content": "hi"}])

    assert result == "Test completion"
    mock_acompletion.assert_called_once()

@pytest.mark.asyncio
@patch("gitresume_core.llm.UnifiedLLMClient.generate_completion", new_callable=AsyncMock)
async def test_generate_json_completion_direct(mock_gen):
    mock_gen.return_value = '{"key": "value"}'

    client = UnifiedLLMClient()
    result = await client.generate_json_completion(messages=[])

    assert result == {"key": "value"}

@pytest.mark.asyncio
@patch("gitresume_core.llm.UnifiedLLMClient.generate_completion", new_callable=AsyncMock)
async def test_generate_json_completion_fallback(mock_gen):
    # Test fallback with markdown block
    mock_gen.return_value = 'Some text\n```json\n{"key": "fallback"}\n```\nmore text'

    client = UnifiedLLMClient()
    result = await client.generate_json_completion(messages=[])

    assert result == {"key": "fallback"}

@pytest.mark.asyncio
@patch("litellm.acompletion")
async def test_generate_completion_error(mock_acompletion):
    mock_acompletion.side_effect = Exception("API Error")

    client = UnifiedLLMClient()
    with pytest.raises(Exception, match="API Error"):
        await client.generate_completion(messages=[])

@pytest.mark.asyncio
@patch("gitresume_core.llm.UnifiedLLMClient.generate_completion", new_callable=AsyncMock)
async def test_generate_json_completion_regex_fallback(mock_gen):
    # Test the last resort regex fallback
    mock_gen.return_value = 'Here is the data: {"key": "regex"}'

    client = UnifiedLLMClient()
    result = await client.generate_json_completion(messages=[])
    assert result == {"key": "regex"}
