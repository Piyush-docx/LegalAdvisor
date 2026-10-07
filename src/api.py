import logging
import os
from typing import Literal, Optional
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.auth import (
    OTPDeliveryError,
    generate_otp,
    get_current_user_optional,
    get_current_user_required,
    get_admin_user,
    verify_otp,
)
from src import store
from src.db import get_admin_logs, save_feedback, using_postgres
from src.guardrails import limiter, redact_pii
from src.pipeline import answer_question
from src.session import default_session_store

logger = logging.getLogger(__name__)

app = FastAPI(title="Legal Help API")
logger.info("storage backend: %s", "PostgreSQL" if using_postgres() else "SQLite (data is lost on redeploy!)")

_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000"
ALLOWED_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


MAX_QUESTION_CHARS = 2000

# (max requests, window in seconds). Per-process limits; see src/guardrails.RateLimiter.
ASK_LIMIT = (int(os.environ.get("ASK_LIMIT_PER_MIN", "15")), 60)
OTP_SEND_PER_EMAIL = (5, 600)
OTP_SEND_PER_IP = (10, 600)
OTP_VERIFY_PER_EMAIL = (5, 600)  # 6-digit codes: this ceiling is what makes brute force impractical
OTP_VERIFY_PER_IP = (20, 600)
FEEDBACK_LIMIT = (30, 60)


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy the socket address is the proxy's; only trust the header when told to.
    if os.environ.get("TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce(key: str, limit_window: tuple[int, int]) -> None:
    limit, window = limit_window
    if not limiter.allow(key, limit, window):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment and try again.",
            headers={"Retry-After": str(window)},
        )


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    session_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    session_id: str


class SendOtpRequest(BaseModel):
    email: str = Field(min_length=3)


class SendOtpResponse(BaseModel):
    message: str


class VerifyOtpRequest(BaseModel):
    email: str = Field(min_length=3)
    otp: str = Field(min_length=4)


class UserInfo(BaseModel):
    id: str
    email: str


class VerifyOtpResponse(BaseModel):
    token: str
    user: UserInfo
    expires_in: int


@app.get("/health")
def health():
    """Liveness probe for the hosting platform. Deliberately touches no database or external service."""
    return {"status": "ok"}


@app.post("/auth/send-otp", response_model=SendOtpResponse)
def send_otp_endpoint(request: SendOtpRequest, http_request: Request) -> SendOtpResponse:
    _enforce(f"otp-send-ip:{_client_ip(http_request)}", OTP_SEND_PER_IP)
    _enforce(f"otp-send-email:{request.email.strip().lower()}", OTP_SEND_PER_EMAIL)
    try:
        generate_otp(request.email)
        return SendOtpResponse(
            message="OTP sent to your email (valid for 10 minutes).",
        )
    except OTPDeliveryError:
        raise HTTPException(
            status_code=502,
            detail="We couldn't send the email right now. Please try again in a few minutes.",
        )
    except Exception:
        logger.exception("Failed to send OTP")
        raise HTTPException(status_code=500, detail="Failed to send OTP.")


@app.post("/auth/verify-otp", response_model=VerifyOtpResponse)
def verify_otp_endpoint(request: VerifyOtpRequest, http_request: Request) -> VerifyOtpResponse:
    _enforce(f"otp-verify-ip:{_client_ip(http_request)}", OTP_VERIFY_PER_IP)
    _enforce(f"otp-verify-email:{request.email.strip().lower()}", OTP_VERIFY_PER_EMAIL)
    result = verify_otp(request.email, request.otp)
    if not result:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")
    return VerifyOtpResponse(
        token=result["token"],
        user=UserInfo(**result["user"]),
        expires_in=result["expires_in"],
    )


@app.get("/auth/me")
def get_me(user: dict = Depends(get_current_user_required)):
    return {"user": user}


@app.get("/sessions")
def get_user_sessions(
    user: dict = Depends(get_current_user_required),
    limit: int = 50,
    offset: int = 0,
):
    if limit > 100:
        limit = 100
    sessions = default_session_store.list_user_sessions(
        user["user_id"], limit=limit, offset=offset
    )
    return {"sessions": sessions, "limit": limit, "offset": offset}


@app.get("/sessions/{session_id}")
def get_session_details(
    session_id: str, user: dict = Depends(get_current_user_required)
):
    session = default_session_store.get(session_id)
    if not session or (session.user_id and session.user_id != user["user_id"]):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {
        "session_id": session.session_id,
        "title": session.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in session.messages
        ],
        "citations": [c.model_dump() for c in session.last_citations],
    }


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.patch("/sessions/{session_id}")
def rename_session_endpoint(
    session_id: str,
    request: RenameSessionRequest,
    user: dict = Depends(get_current_user_required),
):
    success = default_session_store.rename_session(
        session_id, request.title, user["user_id"]
    )
    if not success:
        raise HTTPException(
            status_code=404, detail="Session not found or permission denied."
        )
    return {"message": "Session renamed successfully", "title": request.title}


@app.delete("/sessions/{session_id}")
def delete_session_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user_required),
):
    success = default_session_store.delete_session(session_id, user["user_id"])
    if not success:
        raise HTTPException(
            status_code=404, detail="Session not found or permission denied."
        )
    return {"message": "Session deleted successfully"}


@app.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    http_request: Request,
    current_user: Optional[dict] = Depends(get_current_user_optional),
) -> AskResponse:
    user_id = current_user.get("user_id") if current_user else None
    _enforce(f"ask:{user_id or _client_ip(http_request)}", ASK_LIMIT)
    try:
        if request.session_id or user_id:
            result = answer_question(
                request.question,
                session_id=request.session_id,
                user_id=user_id,
            )
        else:
            result = answer_question(request.question)

        session_id = getattr(
            result, "session_id", request.session_id or str(uuid.uuid4())
        )
        answer_str = str(result)
    except Exception:
        logger.exception("Failed to answer question")
        raise HTTPException(
            status_code=500, detail="Something went wrong. Please try again."
        )
    return AskResponse(answer=answer_str, session_id=session_id)


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer_excerpt: str = Field(min_length=1, max_length=1000)
    session_id: Optional[str] = None
    comment: Optional[str] = Field(default=None, max_length=500)


@app.post("/feedback")
def feedback_endpoint(
    request: FeedbackRequest,
    http_request: Request,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = current_user.get("user_id") if current_user else None
    _enforce(f"feedback:{user_id or _client_ip(http_request)}", FEEDBACK_LIMIT)
    try:
        save_feedback(
            rating=request.rating,
            question=redact_pii(request.question),
            answer_excerpt=redact_pii(request.answer_excerpt),
            session_id=request.session_id,
            user_id=user_id,
            comment=redact_pii(request.comment) if request.comment else None,
        )
    except Exception:
        logger.exception("Failed to save feedback")
        raise HTTPException(status_code=500, detail="Could not save feedback.")
    return {"message": "Thanks for the feedback."}


@app.get("/admin/logs")
def admin_logs_endpoint(user: dict = Depends(get_admin_user)):
    try:
        return get_admin_logs(limit=100)
    except Exception:
        logger.exception("Failed to fetch admin logs")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/admin/answers")
def admin_answers_endpoint(reviewed: bool | None = None, user: dict = Depends(get_admin_user)):
    """Stored answers waiting for review (unreviewed first). Needs PostgreSQL."""
    try:
        return store.list_answers(limit=100, reviewed=reviewed)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="Stored answers need PostgreSQL (DATABASE_URL).")
    except Exception:
        logger.exception("Failed to list stored answers")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.patch("/admin/answers/{answer_id}/review")
def admin_review_answer_endpoint(answer_id: int, reviewed: bool = True, user: dict = Depends(get_admin_user)):
    """Mark a stored answer as human-reviewed, which lets it be served verbatim (tier 1)."""
    try:
        found = store.set_answer_reviewed(answer_id, reviewed)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="Stored answers need PostgreSQL (DATABASE_URL).")
    except Exception:
        logger.exception("Failed to update stored answer")
        raise HTTPException(status_code=500, detail="Internal server error")
    if not found:
        raise HTTPException(status_code=404, detail="No such stored answer.")
    return {"id": answer_id, "reviewed": reviewed}
