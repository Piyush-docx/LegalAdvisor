from unittest.mock import MagicMock, patch

from src.router import (
    RouteIntent,
    can_context_answer_followup,
    classify_intent,
    generate_chitchat_response,
    is_fast_chitchat,
)
from src.session import Session


def test_is_fast_chitchat():
    assert is_fast_chitchat("Hello") is True
    assert is_fast_chitchat("hi!") is True
    assert is_fast_chitchat("Thank you very much") is False  # longer phrase
    assert is_fast_chitchat("thanks") is True
    assert is_fast_chitchat("who are you?") is True
    assert is_fast_chitchat("Can my landlord evict me?") is False


def test_classify_intent_fast_chitchat_avoids_llm():
    session = Session()
    # Fast chit chat should not trigger LLM calls
    intent = classify_intent("hello", session)
    assert intent == RouteIntent.CHITCHAT


@patch("src.router._get_client")
def test_classify_intent_llm_chitchat(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "CHITCHAT"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    session = Session()
    intent = classify_intent("Can you tell me how your site works?", session)
    assert intent == RouteIntent.CHITCHAT


@patch("src.router._get_client")
def test_classify_intent_follow_up(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "FOLLOW_UP"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    session = Session()
    session.last_context_text = "Tenancy Act Section 10: security deposit refund."
    session.add_message("user", "Can my landlord withhold deposit?")
    session.add_message("assistant", "No, it must be refunded.")

    intent = classify_intent("What if they claim painting charges?", session)
    assert intent == RouteIntent.FOLLOW_UP


@patch("src.router._get_client")
def test_classify_intent_new_query(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "NEW_QUERY"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    session = Session()
    intent = classify_intent("What are the rules for workplace harassment in India?", session)
    assert intent == RouteIntent.NEW_QUERY


@patch("src.router._get_client")
def test_can_context_answer_followup_yes(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "YES"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    can_answer = can_context_answer_followup(
        "Is there a 30-day limit?", "The landlord must refund within 30 days of notice."
    )
    assert can_answer is True


@patch("src.router._get_client")
def test_can_context_answer_followup_no(mock_get_client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "NO"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    can_answer = can_context_answer_followup(
        "What about commercial lease?", "This act applies only to residential premises."
    )
    assert can_answer is False


def test_generate_chitchat_response():
    resp_greeting = generate_chitchat_response("hello")
    assert "Indian citizens" in resp_greeting or "everyday legal" in resp_greeting

    resp_thanks = generate_chitchat_response("thanks!")
    assert "welcome" in resp_thanks.lower()
