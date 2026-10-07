import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src import auth
from src.api import app
from src.db import get_db

client = TestClient(app)

SMTP_ENV = {
    "SMTP_HOST": "smtp-relay.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "tech-login@smtp.example.com",
    "SMTP_PASSWORD": "real-key",
    "SMTP_FROM": "verified-sender@example.com",
}


@pytest.fixture
def smtp_env(monkeypatch):
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def no_smtp_env(monkeypatch):
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)


def _otp_count(email):
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM otps WHERE email = ?", (email,)).fetchone()[0]
    conn.close()
    return n


@patch("src.auth.smtplib.SMTP")
def test_email_is_sent_from_the_verified_sender_not_the_login_user(mock_smtp, smtp_env):
    server = mock_smtp.return_value.__enter__.return_value

    auth.send_otp("user@example.com", "123456")

    mock_smtp.assert_called_once_with("smtp-relay.example.com", 587, timeout=auth.SMTP_TIMEOUT_SECONDS)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("tech-login@smtp.example.com", "real-key")
    msg = server.send_message.call_args.args[0]
    assert msg["From"] == "verified-sender@example.com"
    assert msg["To"] == "user@example.com"
    assert "123456" in msg.get_content()


@patch("src.auth.smtplib.SMTP")
def test_sender_falls_back_to_login_user_when_smtp_from_unset(mock_smtp, smtp_env, monkeypatch):
    monkeypatch.delenv("SMTP_FROM")
    server = mock_smtp.return_value.__enter__.return_value

    auth.send_otp("user@example.com", "123456")

    assert server.send_message.call_args.args[0]["From"] == "tech-login@smtp.example.com"


@patch("src.auth.smtplib.SMTP")
def test_smtp_failure_raises_and_leaves_no_usable_code(mock_smtp, smtp_env):
    mock_smtp.return_value.__enter__.return_value.login.side_effect = OSError("535 auth failed")

    with pytest.raises(auth.OTPDeliveryError):
        auth.generate_otp("user@example.com")

    assert _otp_count("user@example.com") == 0


@patch("src.auth.smtplib.SMTP")
def test_api_returns_502_not_a_fake_success_when_email_fails(mock_smtp, smtp_env):
    mock_smtp.return_value.__enter__.return_value.send_message.side_effect = OSError("connection refused")

    response = client.post("/auth/send-otp", json={"email": "user@example.com"})

    assert response.status_code == 502
    assert "couldn't send the email" in response.json()["detail"]


@patch("src.auth.smtplib.SMTP")
def test_api_succeeds_and_stores_code_when_email_sends(mock_smtp, smtp_env):
    response = client.post("/auth/send-otp", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert _otp_count("user@example.com") == 1
    mock_smtp.return_value.__enter__.return_value.send_message.assert_called_once()


@patch("src.auth.smtplib.SMTP")
def test_without_smtp_settings_code_is_printed_visibly_and_no_mail_is_attempted(mock_smtp, no_smtp_env, caplog):
    with caplog.at_level(logging.WARNING, logger="src.auth"):
        auth.send_otp("user@example.com", "654321")

    mock_smtp.assert_not_called()
    assert "654321" in caplog.text and "dev only" in caplog.text
