import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import responses

from src.pipeline import answer_question

FIXTURES = Path(__file__).parent / "fixtures"


def make_fake_llm_response(text="The security deposit must be refunded upon vacating."):
    candidate = MagicMock()
    candidate.finish_reason.name = "STOP"

    response = MagicMock()
    response.text = text
    response.candidates = [candidate]
    response.usage_metadata = MagicMock(prompt_token_count=2000, candidates_token_count=200)
    return response


@responses.activate
@patch("src.retrieval.context.rewrite_query", side_effect=lambda q: q)
@patch("src.generation.generate.genai.Client")
def test_answer_question_end_to_end(mock_client_cls, mock_rewrite, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")

    search_fixture = json.loads((FIXTURES / "search_response.json").read_text())
    doc_fixture = json.loads((FIXTURES / "document_response.json").read_text())

    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=search_fixture,
        status=200,
    )
    for doc in search_fixture["docs"][:5]:
        responses.add(
            responses.POST,
            f"https://api.indiankanoon.org/doc/{doc['tid']}/",
            json={**doc_fixture, "tid": doc["tid"]},
            status=200,
        )

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = make_fake_llm_response()
    mock_client_cls.return_value = mock_client

    result = answer_question("security deposit refund tenant landlord")

    assert "The security deposit must be refunded upon vacating." in result
    assert "indian kanoon" in result.lower() or "ikanoon" in result.lower()
    assert "lawyer" in result.lower()
    assert "Hs Bedi" in result  # citation from the first search result
