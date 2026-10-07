from enum import Enum
import os
import re

from google import genai
from google.genai import types

from src.session import Session

MODEL = "gemini-2.5-flash"

_client = None


def _get_client():
    global _client
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        return None
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


class RouteIntent(str, Enum):
    CHITCHAT = "CHITCHAT"
    FOLLOW_UP = "FOLLOW_UP"
    NEW_QUERY = "NEW_QUERY"


FAST_CHITCHAT_PATTERNS = {
    "hi",
    "hello",
    "hey",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
    "thx",
    "bye",
    "goodbye",
    "who are you",
    "what can you do",
    "help",
    "help me",
    "ok",
    "okay",
}

ROUTER_PROMPT = """\
You are an intent classifier for a citizen legal assistance service for Indian law.
Classify the user's message into one of three categories:
- CHITCHAT: greetings, polite remarks, thanks, meta-questions about the AI/service ("who are you", "how does this work"), or casual conversation.
- FOLLOW_UP: questions or statements that continue or clarify the ongoing legal topic from previous turns (e.g. asking for exceptions, timelines, deductions, or next steps on the same dispute). Only choose this if previous conversation context exists and the user is continuing that topic.
- NEW_QUERY: a substantive legal question (either starting a topic or switching to an unrelated area of law).

Previous conversation:
{conversation_summary}

User message: "{message}"

Respond with ONLY one word: CHITCHAT, FOLLOW_UP, or NEW_QUERY."""

CONTEXT_CHECK_PROMPT = """\
Given the retrieved Indian legal text below, can the user's question be substantially answered from this text?

RETRIEVED TEXT:
{context_snippet}

QUESTION:
{question}

Respond with ONLY one word: YES or NO."""


def is_fast_chitchat(message: str) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", message).strip().lower()
    return cleaned in FAST_CHITCHAT_PATTERNS


def format_conversation_summary(session: Session, max_turns: int = 4) -> str:
    if not session.messages:
        return "None (new conversation)"
    recent = session.messages[-max_turns:]
    return "\n".join(f"{m.role.capitalize()}: {m.content[:200]}" for m in recent)


def classify_intent(message: str, session: Session) -> RouteIntent:
    if is_fast_chitchat(message):
        return RouteIntent.CHITCHAT

    if not session.messages and not session.last_context_text:
        summary = "None (new conversation)"
    else:
        summary = format_conversation_summary(session)

    client = _get_client()
    if not client:
        return RouteIntent.FOLLOW_UP if session.last_context_text else RouteIntent.NEW_QUERY

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=ROUTER_PROMPT.format(conversation_summary=summary, message=message),
            config=types.GenerateContentConfig(
                max_output_tokens=16,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw_text = (response.text or "").strip().upper()
        if "CHITCHAT" in raw_text:
            return RouteIntent.CHITCHAT
        if "FOLLOW_UP" in raw_text and session.last_context_text:
            return RouteIntent.FOLLOW_UP
        return RouteIntent.NEW_QUERY
    except Exception:
        # Fallback gracefully
        if session.last_context_text:
            return RouteIntent.FOLLOW_UP
        return RouteIntent.NEW_QUERY


def can_context_answer_followup(question: str, context_text: str) -> bool:
    """Check if existing retrieved text has sufficient substance to answer a follow-up."""
    if not context_text or not context_text.strip():
        return False

    try:
        client = _get_client()
        if not client:
            return False
        snippet = context_text[:3000]
        response = client.models.generate_content(
            model=MODEL,
            contents=CONTEXT_CHECK_PROMPT.format(context_snippet=snippet, question=question),
            config=types.GenerateContentConfig(
                max_output_tokens=10,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw_text = (response.text or "").strip().upper()
        return "YES" in raw_text
    except Exception:
        return False


def generate_chitchat_response(message: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", message).strip().lower()
    if cleaned in {"thanks", "thank you", "thx"}:
        return (
            "You're very welcome! If you have any more questions about your rights or "
            "Indian legal procedures, please feel free to ask."
        )
    if cleaned in {"bye", "goodbye"}:
        return (
            "Goodbye! Wishing you the best. Remember to consult a qualified lawyer "
            "for specific legal action or advice."
        )

    return (
        "Hello! I am an assistant designed to help Indian citizens understand their rights, "
        "relevant laws, and legal procedures in plain language.\n\n"
        "You can ask me questions about everyday legal issues such as:\n"
        "• Tenancy & landlord disputes (security deposits, eviction, rent)\n"
        "• Employment & labor rights (unpaid wages, notice periods, termination)\n"
        "• Consumer complaints (defective goods, service deficiency, refunds)\n"
        "• Family and property matters\n\n"
        "What legal situation or question can I help you with today?"
    )
