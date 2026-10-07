from unittest.mock import MagicMock, patch

import pytest

from src.generation.generate import explain_with_llm
from src.generation.schemas import LLMAnswer
from src.retrieval.context import Citation


def make_citation():
    return Citation(
        title="Hs Bedi vs NHAI on 14 May, 2015",
        docsource="Delhi High Court",
        publishdate="2015-05-14",
        url="https://indiankanoon.org/doc/183757259/",
    )


def make_fake_response(text="The security deposit must be refunded.", finish_reason="STOP"):
    candidate = MagicMock()
    candidate.finish_reason.name = finish_reason

    response = MagicMock()
    response.text = text
    response.candidates = [candidate]
    response.usage_metadata = MagicMock(prompt_token_count=1200, candidates_token_count=150)
    return response


@patch("src.generation.generate._get_client")
def test_explain_with_llm_returns_validated_answer(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_response()
    mock_get_client.return_value = mock_client

    result = explain_with_llm(
        question="Can my landlord keep my deposit?",
        context_text="The security deposit must be refunded upon vacating.",
        citations=[make_citation()],
    )

    assert isinstance(result, LLMAnswer)
    assert result.text == "The security deposit must be refunded."
    assert result.stop_reason == "STOP"
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 150


@patch("src.generation.generate._get_client")
def test_explain_with_llm_uses_gemini_flash_model(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_response()
    mock_get_client.return_value = mock_client

    explain_with_llm(
        question="q",
        context_text="context",
        citations=[make_citation()],
    )

    _, kwargs = mock_client.models.generate_content.call_args
    assert kwargs["model"] == "gemini-2.5-flash"


@patch("src.generation.generate._get_client")
def test_explain_with_llm_passes_api_key_from_env(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "the-secret-key")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_response()
    mock_get_client.return_value = mock_client

    explain_with_llm(question="q", context_text="context", citations=[make_citation()])

    # The _get_client function was called, meaning the module-level client is used
    mock_get_client.assert_called_once()


@patch("src.generation.generate._get_client")
def test_explain_with_llm_raises_on_empty_response_text(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    mock_client = MagicMock()
    empty_response = make_fake_response(text=None, finish_reason="SAFETY")
    mock_client.models.generate_content.return_value = empty_response
    mock_get_client.return_value = mock_client

    with pytest.raises(Exception):
        explain_with_llm(question="q", context_text="context", citations=[make_citation()])
