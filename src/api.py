import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.pipeline import answer_question

logger = logging.getLogger(__name__)

app = FastAPI(title="Legal Help API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    answer: str


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        answer = answer_question(request.question)
    except Exception:
        logger.exception("Failed to answer question")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")
    return AskResponse(answer=answer)
