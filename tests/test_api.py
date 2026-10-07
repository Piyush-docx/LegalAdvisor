from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app
from src.auth import create_auth_token
from src.session import AnswerWithSession

client = TestClient(app)


@patch("src.api.answer_question")
def test_ask_returns_answer_for_valid_question(mock_answer_question):
    mock_answer_question.return_value = "The security deposit must be refunded.\n\nSources:\n..."

    response = client.post("/ask", json={"question": "Can my landlord keep my deposit?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The security deposit must be refunded.\n\nSources:\n..."
    assert "session_id" in body
    assert body["session_id"] is not None
    mock_answer_question.assert_called_once_with("Can my landlord keep my deposit?")


@patch("src.api.answer_question")
def test_ask_forwards_provided_session_id(mock_answer_question):
    mock_answer_question.return_value = AnswerWithSession("Sample answer", "my-existing-session-123")

    response = client.post(
        "/ask",
        json={
            "question": "What if they deduct money?",
            "session_id": "my-existing-session-123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Sample answer"
    assert body["session_id"] == "my-existing-session-123"
    mock_answer_question.assert_called_once_with(
        "What if they deduct money?", session_id="my-existing-session-123", user_id=None
    )


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


@patch("src.api.generate_otp")
def test_send_and_verify_otp_flow(mock_generate_otp):
    from src.auth import generate_otp as real_generate_otp

    captured = {}

    def fake_generate_otp(email, db_conn=None):
        code = real_generate_otp(email, db_conn=db_conn)
        captured["otp"] = code
        return code

    mock_generate_otp.side_effect = fake_generate_otp

    # Send OTP
    resp_send = client.post("/auth/send-otp", json={"email": "tester@example.com"})
    assert resp_send.status_code == 200
    body_send = resp_send.json()
    assert "dev_otp" not in body_send
    otp = captured["otp"]

    # Verify OTP
    resp_verify = client.post(
        "/auth/verify-otp", json={"email": "tester@example.com", "otp": otp}
    )
    assert resp_verify.status_code == 200
    body_verify = resp_verify.json()
    assert "token" in body_verify
    assert body_verify["user"]["email"] == "tester@example.com"
    assert body_verify["expires_in"] == 86400

    token = body_verify["token"]

    # Access /auth/me with Bearer token
    resp_me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp_me.status_code == 200
    assert resp_me.json()["user"]["email"] == "tester@example.com"

    # Unauthorized access to /auth/me
    resp_unauth = client.get("/auth/me")
    assert resp_unauth.status_code == 401


def test_get_sessions_requires_auth():
    resp = client.get("/sessions")
    assert resp.status_code == 401

    token = create_auth_token("user@example.com", "usr-123")
    resp_authed = client.get(
        "/sessions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_authed.status_code == 200
    assert "sessions" in resp_authed.json()
