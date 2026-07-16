from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


@patch("src.api.answer_question")
def test_ask_returns_answer_for_valid_question(mock_answer_question):
    mock_answer_question.return_value = "The security deposit must be refunded.\n\nSources:\n..."

    response = client.post("/ask", json={"question": "Can my landlord keep my deposit?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The security deposit must be refunded.\n\nSources:\n..."
    mock_answer_question.assert_called_once_with("Can my landlord keep my deposit?")


def test_ask_rejects_empty_question():
    response = client.post("/ask", json={"question": ""})

    assert response.status_code == 422


def test_ask_rejects_missing_question_field():
    response = client.post("/ask", json={})

    assert response.status_code == 422


@patch("src.api.answer_question")
def test_ask_returns_500_with_safe_message_on_pipeline_failure(mock_answer_question):
    mock_answer_question.side_effect = RuntimeError("IKanoon API key invalid or exhausted")

    response = client.post("/ask", json={"question": "some question"})

    assert response.status_code == 500
    body = response.json()
    # The safe error message must not leak internal exception details
    assert "IKanoon API key" not in body["detail"]
    assert "invalid or exhausted" not in body["detail"]
