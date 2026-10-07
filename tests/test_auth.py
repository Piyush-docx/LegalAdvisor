from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.auth import (
    create_auth_token,
    generate_otp,
    verify_auth_token,
    verify_otp,
)
from src.db import init_db


def test_otp_generation_and_verification(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_auth.db")
    monkeypatch.setattr("src.db.DB_PATH", test_db)
    init_db(test_db)

    email = "citizen@example.com"
    code = generate_otp(email)
    assert len(code) == 6
    assert code.isdigit()

    # Wrong code fails
    assert verify_otp(email, "000000") is None

    # Correct code succeeds and creates token
    result = verify_otp(email, code)
    assert result is not None
    assert "token" in result
    assert result["user"]["email"] == email
    assert result["expires_in"] == 86400

    # Token can be verified
    payload = verify_auth_token(result["token"])
    assert payload is not None
    assert payload["email"] == email
    assert payload["user_id"] == result["user"]["id"]

    # Reusing same code fails
    assert verify_otp(email, code) is None


def test_otp_expiration(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_auth_exp.db")
    monkeypatch.setattr("src.db.DB_PATH", test_db)
    init_db(test_db)

    email = "expired@example.com"
    code = generate_otp(email)

    # Simulate expired OTP
    from src.db import get_db

    conn = get_db(test_db)
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    conn.execute(
        "UPDATE otps SET expires_at = ? WHERE email = ?", (past_iso, email)
    )
    conn.commit()
    conn.close()

    assert verify_otp(email, code) is None


def test_auth_token_24_hour_expiry():
    email = "user@example.com"
    user_id = "user-123"
    token = create_auth_token(email, user_id)

    # Fresh token verifies ok
    payload = verify_auth_token(token)
    assert payload["email"] == email

    # Manipulated or expired token fails
    assert verify_auth_token("invalid.token.here") is None
