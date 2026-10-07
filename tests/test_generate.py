from unittest.mock import patch

from src.generation.generate import explain_with_llm, trim_incomplete
from src.generation.schemas import LLMAnswer
from src.llm import LLMUnavailable
from src.retrieval.context import Citation
from tests.helpers import llm_result

import pytest


def make_citation():
    return Citation(
        title="Hs Bedi vs NHAI on 14 May, 2015",
        docsource="Delhi High Court",
        publishdate="2015-05-14",
        url="https://indiankanoon.org/doc/183757259/",
    )


@patch("src.generation.generate.complete")
def test_explain_with_llm_returns_validated_answer(mock_complete):
    mock_complete.return_value = llm_result("The security deposit must be refunded.", tokens_in=1200, tokens_out=150)

    result = explain_with_llm(
        question="Can my landlord keep my deposit?",
        context_text="The security deposit must be refunded upon vacating.",
        citations=[make_citation()],
    )

    assert isinstance(result, LLMAnswer)
    assert result.text == "The security deposit must be refunded."
    assert result.stop_reason == "STOP" and result.truncated is False
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 150


@patch("src.generation.generate.complete")
def test_explain_with_llm_uses_the_answer_task_and_prompt(mock_complete):
    mock_complete.return_value = llm_result()

    explain_with_llm("my question", "the context", [make_citation()])

    task, prompt = mock_complete.call_args.args
    assert task == "answer"
    assert "my question" in prompt and "the context" in prompt
    assert mock_complete.call_args.kwargs["max_tokens"] >= 4096


@patch("src.generation.generate.complete", side_effect=LLMUnavailable("all models failed"))
def test_explain_with_llm_propagates_unavailable(mock_complete):
    with pytest.raises(LLMUnavailable):
        explain_with_llm("q", "ctx", [make_citation()])


def test_trim_incomplete_cuts_back_to_last_complete_sentence():
    assert trim_incomplete("First point. Second point. Third poi") == "First point. Second point."
    assert trim_incomplete("Intro line\n**Mediation") == "Intro line"
    assert trim_incomplete("No terminator here") == "No terminator here"


@patch("src.generation.generate.complete")
def test_explain_with_llm_flags_and_repairs_truncated_answer(mock_complete):
    mock_complete.return_value = llm_result("Complete sentence. Cut off mid-wo", stop="MAX_TOKENS")

    result = explain_with_llm("q", "ctx", [make_citation()])

    assert result.truncated is True
    assert result.stop_reason == "MAX_TOKENS"
    assert "mid-wo" not in result.text
    assert result.text.startswith("Complete sentence.")
    assert "shortened" in result.text
