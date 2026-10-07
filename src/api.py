import logging
from typing import Optional
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.auth import (
    generate_otp,
    get_current_user_optional,
    get_current_user_required,
    get_admin_user,
    verify_otp,
)
from src.db import get_admin_logs
from src.pipeline import answer_question
from src.session import default_session_store

logger = logging.getLogger(__name__)

app = FastAPI(title="Legal Help API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    session_id: str


class SendOtpRequest(BaseModel):
    email: str = Field(min_length=3)


class SendOtpResponse(BaseModel):
    message: str
    dev_otp: Optional[str] = None


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


@app.post("/auth/send-otp", response_model=SendOtpResponse)
def send_otp_endpoint(request: SendOtpRequest) -> SendOtpResponse:
    try:
        code = generate_otp(request.email)
        return SendOtpResponse(
            message="OTP sent to your email (valid for 10 minutes).",
            dev_otp=code,
        )
    except Exception:
        logger.exception("Failed to send OTP")
        raise HTTPException(status_code=500, detail="Failed to send OTP.")


@app.post("/auth/verify-otp", response_model=VerifyOtpResponse)
def verify_otp_endpoint(request: VerifyOtpRequest) -> VerifyOtpResponse:
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
    current_user: Optional[dict] = Depends(get_current_user_optional),
) -> AskResponse:
    user_id = current_user.get("user_id") if current_user else None
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


@app.get("/admin/logs")
def admin_logs_endpoint(user: dict = Depends(get_admin_user)):
    try:
        return get_admin_logs(limit=100)
    except Exception:
        logger.exception("Failed to fetch admin logs")
        raise HTTPException(status_code=500, detail="Internal server error")
