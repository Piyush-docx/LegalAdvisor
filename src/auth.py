from datetime import datetime, timedelta, timezone
import logging
import os
import secrets
import smtplib
from email.message import EmailMessage
from typing import Optional
import uuid

from fastapi import Header, HTTPException
from itsdangerous import URLSafeTimedSerializer

from src.db import get_db

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("AUTH_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "AUTH_SECRET_KEY not set — generated a random ephemeral key. "
        "Tokens will NOT survive server restarts. Set AUTH_SECRET_KEY in .env for production."
    )
TOKEN_EXPIRY_SECONDS = 86400  # 24 hours / 1 day
OTP_VALIDITY_MINUTES = 10

serializer = URLSafeTimedSerializer(SECRET_KEY, salt="auth-token")

SMTP_TIMEOUT_SECONDS = 15


class OTPDeliveryError(Exception):
    """The login code could not be emailed."""


def create_auth_token(email: str, user_id: str) -> str:
    """Generate a signed auth token with payload valid for 24 hours (1 day)."""
    return serializer.dumps({"email": email.strip().lower(), "user_id": user_id})


def verify_auth_token(token: str) -> Optional[dict]:
    """Verify auth token, enforcing 24-hour maximum age."""
    try:
        data = serializer.loads(token, max_age=TOKEN_EXPIRY_SECONDS)
        return data
    except Exception:
        return None


def generate_otp(email: str, db_conn=None) -> str:
    """Generate a 6-digit numeric OTP and store in database with 10-minute expiry."""
    normalized_email = email.strip().lower()
    otp_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=OTP_VALIDITY_MINUTES)
    ).isoformat()

    conn = db_conn or get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO otps (email, otp_code, expires_at, used) VALUES (?, ?, ?, 0)",
                (normalized_email, otp_code, expires_at),
            )
    finally:
        if not db_conn:
            conn.close()

    try:
        send_otp(normalized_email, otp_code)
    except OTPDeliveryError:
        # Don't leave a valid code behind that the user never received.
        conn = db_conn or get_db()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM otps WHERE email = ? AND otp_code = ? AND used = 0",
                    (normalized_email, otp_code),
                )
        finally:
            if not db_conn:
                conn.close()
        raise
    return otp_code


def smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_otp(email: str, code: str) -> None:
    """Email the code over SMTP. Without SMTP settings (local dev only) print it to the terminal.

    Raises OTPDeliveryError if SMTP is configured but sending fails, so the API never claims
    a code was sent when it was not."""
    if not smtp_configured():
        logger.warning("SMTP is not configured: OTP for %s is %s (dev only)", _mask_email(email), code)
        return

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    # Providers such as Brevo log in with a technical username; the visible sender must be a
    # verified address, which is what SMTP_FROM is for.
    sender = os.environ.get("SMTP_FROM") or smtp_user

    msg = EmailMessage()
    msg["Subject"] = "Your Legal Help Login Code"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(
        f"Your Legal Help login code is: {code}\n\n"
        f"This code will expire in {OTP_VALIDITY_MINUTES} minutes.\n"
        "If you did not request this code, please ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(smtp_user, os.environ["SMTP_PASSWORD"])
            server.send_message(msg)
    except Exception as exc:
        logger.error("Failed to send OTP email to %s: %s: %s", _mask_email(email), type(exc).__name__, exc)
        raise OTPDeliveryError(str(exc)) from exc
    logger.info("OTP email sent to %s", _mask_email(email))


def _mask_email(email: str) -> str:
    """Mask email for safe logging, e.g. 'pi***@gmail.com'."""
    parts = email.split("@")
    if len(parts) != 2 or len(parts[0]) < 2:
        return "***"
    return parts[0][:2] + "***@" + parts[1]


def verify_otp(email: str, code: str, db_conn=None) -> Optional[dict]:
    """Verify an OTP code, create user if new, and return 24-hour auth token."""
    normalized_email = email.strip().lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = db_conn or get_db()
    user_id = None
    try:
        with conn:
            cursor = conn.execute(
                """
                SELECT id, otp_code, expires_at, used
                FROM otps
                WHERE email = ? AND otp_code = ? AND used = 0
                ORDER BY id DESC LIMIT 1
                """,
                (normalized_email, code.strip()),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Check expiration
            if row["expires_at"] < now_iso:
                return None

            # Mark OTP as used
            conn.execute("UPDATE otps SET used = 1 WHERE id = ?", (row["id"],))

            # Check or create user
            cursor = conn.execute(
                "SELECT id, email FROM users WHERE email = ?", (normalized_email,)
            )
            user_row = cursor.fetchone()
            if user_row:
                user_id = user_row["id"]
            else:
                user_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                    (user_id, normalized_email, now_iso),
                )
    finally:
        if not db_conn:
            conn.close()

    if not user_id:
        return None

    token = create_auth_token(normalized_email, user_id)
    return {
        "token": token,
        "user": {"id": user_id, "email": normalized_email},
        "expires_in": TOKEN_EXPIRY_SECONDS,
    }


def get_current_user_optional(
    authorization: Optional[str] = Header(None),
) -> Optional[dict]:
    """FastAPI dependency: extracts user payload if Authorization Bearer token is valid."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return verify_auth_token(parts[1])


def get_current_user_required(
    authorization: Optional[str] = Header(None),
) -> dict:
    """FastAPI dependency: requires valid 24-hour Authorization Bearer token."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required or token expired (valid for 24 hours).",
        )
    return user


def get_admin_user(
    authorization: Optional[str] = Header(None),
) -> dict:
    """FastAPI dependency: requires valid 24-hour Authorization Bearer token AND admin email."""
    user = get_current_user_required(authorization)
    
    admin_emails_env = os.environ.get("ADMIN_EMAILS", "")
    admin_emails = [e.strip().lower() for e in admin_emails_env.split(",") if e.strip()]
    
    if user["email"] not in admin_emails:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. Admin access required.",
        )
        
    return user
