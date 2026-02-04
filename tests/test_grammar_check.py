import pytest
from unittest.mock import patch, AsyncMock
from gitresume_core.grammar_check import LocalGrammarFixer, AIGrammarChecker, correct_resume_grammar

def test_local_grammar_fixer_spacing():
    text = "Hello  world .  This  is  a test!"
    fixed = LocalGrammarFixer.fix_spacing_and_punctuation(text)
    assert fixed == "Hello world. This is a test!"

def test_local_grammar_fixer_punctuation():
    text = "Hello world ! How are you ?"
    fixed = LocalGrammarFixer.fix_spacing_and_punctuation(text)
    assert fixed == "Hello world! How are you?"

@pytest.mark.asyncio
@patch("gitresume_core.llm.UnifiedLLMClient.generate_completion", new_callable=AsyncMock)
async def test_ai_grammar_checker(mock_gen):
    mock_gen.return_value = "Corrected text"
    checker = AIGrammarChecker()
    result = await checker.correct_text_async("original text")
    assert result == "Corrected text"

@pytest.mark.asyncio
@patch("gitresume_core.grammar_check.text_processor")
async def test_correct_resume_grammar(mock_processor, mock_llm):
    # Mock the processor's process_jobs method
    async def mock_process_jobs(jobs):
        for job in jobs:
            # The job.update_func expects the corrected combined text
            # In our case, correct_resume_grammar combines texts with SEP
            job.update_func("Corrected Title\n<--SEP-->\nCorrected Note")

    mock_processor.process_jobs = AsyncMock(side_effect=mock_process_jobs)

    resume_data = {
        "project_title": "Old Title",
        "additional_notes": "Old Note",
        "bullet_points": []
    }

    result = await correct_resume_grammar(resume_data)
    assert result["project_title"] == "Corrected Title"
    assert result["additional_notes"] == "Corrected Note"

@pytest.mark.asyncio
@patch("gitresume_core.grammar_check.text_processor")
async def test_correct_resume_grammar_interview_questions(mock_processor):
    async def mock_process_jobs(jobs):
        for job in jobs:
            job.update_func("Q1 Corrected\n<--SEP-->\nA1 Corrected")

    mock_processor.process_jobs = AsyncMock(side_effect=mock_process_jobs)

    resume_data = {
        "interview_questions": [
            {"question": "Q1", "answer": "A1"}
        ]
    }

    result = await correct_resume_grammar(resume_data)
    assert result["interview_questions"][0]["question"] == "Q1 Corrected"
    assert result["interview_questions"][0]["answer"] == "A1 Corrected"

def test_local_grammar_fixer_empty():
    assert LocalGrammarFixer.fix_spacing_and_punctuation("") == ""
    assert LocalGrammarFixer.fix_spacing_and_punctuation(None) is None

@pytest.mark.asyncio
async def test_ai_grammar_checker_empty():
    checker = AIGrammarChecker()
    assert await checker.correct_text_async("") == ""
    assert await checker.correct_text_async("   ") == "   "
