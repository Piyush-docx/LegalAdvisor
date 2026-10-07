from unittest.mock import MagicMock, patch

from src.retrieval.rewrite import rewrite_query


def make_fake_response(text):
    response = MagicMock()
    response.text = text
    return response


@patch("src.retrieval.rewrite._get_client")
def test_rewrite_query_returns_model_output_stripped(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_response(
        '"security deposit" ANDD tenancy\n'
    )
    mock_get_client.return_value = mock_client

    result = rewrite_query("my landlord is asking a huge deposit")

    assert result == '"security deposit" ANDD tenancy'


@patch("src.retrieval.rewrite._get_client")
def test_rewrite_query_falls_back_to_question_on_empty_output(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_response(None)
    mock_get_client.return_value = mock_client

    result = rewrite_query("my landlord is asking a huge deposit")

    assert result == "my landlord is asking a huge deposit"
