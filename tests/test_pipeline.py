import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import responses

from src.pipeline import answer_question
from src.session import SessionStore
from tests.helpers import llm_result

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
@patch("src.pipeline.rewrite_query", side_effect=lambda q, **kwargs: q)
@patch("src.generation.generate.complete")
def test_answer_question_end_to_end(mock_complete, mock_rewrite, monkeypatch):
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

    mock_complete.return_value = llm_result("The security deposit must be refunded upon vacating.", tokens_in=2000, tokens_out=200)

    result = answer_question("security deposit refund tenant landlord")

    assert "The security deposit must be refunded upon vacating." in result
    assert "indian kanoon" in result.lower() or "ikanoon" in result.lower()
    assert "lawyer" in result.lower()
    assert "Hs Bedi" in result  # citation from the first search result


@responses.activate
@patch("src.pipeline.classify_intent")
def test_answer_question_chitchat_makes_no_ikanoon_calls(mock_classify):
    from src.router import RouteIntent
    mock_classify.return_value = RouteIntent.CHITCHAT
    # Calling with a greeting should NOT trigger any HTTP calls to Indian Kanoon
    result = answer_question("Hello, who are you?")
    assert "everyday legal" in result or "Indian citizens" in result
    assert len(responses.calls) == 0


@responses.activate
@patch("src.pipeline.can_context_answer_followup", return_value=True)
@patch("src.pipeline.classify_intent")
@patch("src.generation.generate.complete")
def test_answer_question_followup_reuses_context(
    mock_complete, mock_classify, mock_can_answer, monkeypatch
):
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    from src.router import RouteIntent

    mock_classify.return_value = RouteIntent.FOLLOW_UP
    mock_complete.return_value = llm_result("Follow-up answer based on existing context.")

    store = SessionStore()
    sess = store.create()
    sess.last_context_text = "Retrieved tenancy law provisions."
    from src.retrieval.context import Citation

    sess.last_citations = [
        Citation(
            title="Sample Case",
            docsource="Delhi HC",
            publishdate="2021-01-01",
            url="https://indiankanoon.org/doc/999/",
        )
    ]
    store.save(sess)

    result = answer_question(
        "Can they deduct cleaning fee?",
        session_id=sess.session_id,
        session_store=store,
    )

    assert "Follow-up answer based on existing context." in result
    assert "Sample Case" in result
    # Zero calls to Indian Kanoon because existing context was reused!
    assert len(responses.calls) == 0


def test_answer_question_returns_session_id_when_requested():
    store = SessionStore()
    answer, session_id = answer_question(
        "hi", return_session=True, session_store=store
    )
    assert isinstance(answer, str)
    assert isinstance(session_id, str)
    assert len(session_id) > 10
