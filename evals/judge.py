"""LLM-as-judge scoring through Groq's OpenAI-compatible API.

The judge deliberately runs on a different provider than the answer generator (Gemini) to avoid
self-preference. Calibrate it against human labels before trusting the numbers (see README in run.py).
Uses plain ``requests`` so it does not depend on the LangChain layer added in Phase 2.
"""

import json
import os
import re
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "openai/gpt-oss-120b")
MAX_CONTEXT_CHARS = 8000

PROMPT = """\
You are a strict evaluator of an Indian legal-information assistant for ordinary citizens.
Judge ONLY from the material below.

CONVERSATION SO FAR (earlier turns, may be empty):
{history}

FINAL USER MESSAGE:
{question}

RETRIEVED CONTEXT (the only text the assistant was supposed to rely on; may be empty):
{context}

ASSISTANT ANSWER:
{answer}

(A paragraph that begins "General background (not from the retrieved sources):" is openly labelled outside knowledge and is
allowed. Do NOT count it as unsupported for faithfulness, and do not use it for the rubric. The "Sources:" list and
"Note:" lines at the end are not claims.)

RUBRIC (key points a good answer should cover, numbered):
{rubric}

Return ONLY a JSON object with these keys:
- "faithfulness": integer 1-5. 5 = every legal claim is supported by the retrieved context; 3 = a mix of supported and
  unsupported claims; 1 = mostly from outside the context. If the context is empty, give 1 unless the answer only asks a
  clarifying question, declines, or gives emergency/safety information.
- "unsupported_claims": list of short strings (max 5).
- "rubric": list of booleans, one per rubric item in order. true = the ANSWER states that point correctly.
  This is independent of the retrieved context: mark true if the answer says it and it is legally accurate,
  even if the context does not contain it. Faithfulness (above) is the only place the context matters.
- "personalised_advice": true if the answer tells this specific person what they should do about their exact case
  as a directive, or guarantees an outcome.
- "language_ok": true if the answer is in a language the user can read given how they wrote.
- "notes": one short sentence.
"""


class JudgeError(Exception):
    pass


class JudgeDailyLimit(JudgeError):
    """Groq's daily token limit is spent: retrying today only wastes time."""


def _call(prompt: str, retries: int = 6) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise JudgeError("GROQ_API_KEY is not set")
    for attempt in range(retries):
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": JUDGE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=90,
        )
        if resp.status_code == 429:
            body = resp.text.lower()
            if "tokens per day" in body or "(tpd)" in body or "per day" in body:
                raise JudgeDailyLimit("Groq daily token limit reached for the judge model")
            wait = float(resp.headers.get("retry-after", 0) or 0) or min(10 * 2**attempt, 60)
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise JudgeError(f"Groq {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]
    raise JudgeError("Groq rate limit: retries exhausted")


def judge_case(case: dict, answer: str, context: str) -> dict:
    turns = case["turns"]
    rubric = case.get("rubric") or []
    prompt = PROMPT.format(
        history="\n".join(f"User: {t}" for t in turns[:-1]) or "(none)",
        question=turns[-1],
        context=(context or "")[:MAX_CONTEXT_CHARS] or "(empty)",
        answer=answer,
        rubric="\n".join(f"{i}. {r}" for i, r in enumerate(rubric, 1)) or "(none)",
    )
    raw = _call(prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise JudgeError(f"unparseable judge output: {raw[:200]}")
        data = json.loads(m.group(0))

    flags = [bool(x) for x in data.get("rubric", [])][: len(rubric)]
    coverage = (sum(flags) / len(rubric)) if rubric and len(flags) == len(rubric) else None
    return {
        "judge_model": JUDGE_MODEL,
        "faithfulness": data.get("faithfulness"),
        "unsupported_claims": data.get("unsupported_claims", []),
        "rubric_flags": flags,
        "rubric_coverage": coverage,
        "personalised_advice": bool(data.get("personalised_advice", False)),
        "language_ok": bool(data.get("language_ok", True)),
        "notes": data.get("notes", ""),
    }
