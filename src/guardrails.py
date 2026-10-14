"""Guardrails for the legal-help pipeline: plain, dependency-free functions.

Layers (see docs/phase_1_guardrails_walkthrough.md):
  input     PII redaction, harm-signal detection (keyword path works with no LLM), prompt-attack
            detection, delimiting of untrusted text
  retrieval "no sources found" response, daily IKanoon call budget
  output    prompt-leak check, unverified-section note, outcome-language note, repealed-statute
            note, legal-aid pointer for high-risk topics
  abuse     in-memory sliding-window rate limiter (per process)
"""

import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import date
from enum import Enum

logger = logging.getLogger(__name__)

# --- Helplines -------------------------------------------------------------------------------
# VERIFY EVERY NUMBER BEFORE LAUNCH. Numbers change; a wrong helpline in a safety message is worse
# than none. They live in one place on purpose.
HELPLINES = {
    "emergency": "112",
    "women": "181",
    "child": "1098",
    "mental_health": "14416",  # Tele-MANAS
    "legal_aid": "15100",  # NALSA
    "cyber_fraud": "1930",
}


# --- PII redaction ---------------------------------------------------------------------------
_PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[-\s]?|0)?[6-9]\d{4}[-\s]?\d{5}(?!\d)")),
]


def redact_pii(text: str) -> str:
    """Replace emails, PAN, Aadhaar and Indian phone numbers with placeholders."""
    for label, pattern in _PII_PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


# --- Harm signals ----------------------------------------------------------------------------
class Harm(str, Enum):
    SELF_HARM = "self_harm"
    DOMESTIC_VIOLENCE = "domestic_violence"
    CHILD_ABUSE = "child_abuse"


_SELF_HARM = re.compile(
    r"\b(kill(ing)? myself|end(ing)? my (own )?life|take my own life|want to die|"
    r"(thinking of|going to|plan(ning)? to) (commit )?suicide|i am suicidal|i'm suicidal|"
    r"khudkushi|jaan de (dunga|dungi)|marna chah(ta|ti) hu)\b",
    re.IGNORECASE,
)
_DOMESTIC_VIOLENCE = re.compile(
    r"\b(beats?|beating|hits?|hitting|slaps?|abus(es|ing)|chokes?|chok(ing)|tortur(es|ing)) me\b|"
    r"\b(threatens?|threatening|going) to kill me\b|scared for my life|"
    r"mujhe (maar|maarta|peet|peetta)|maar ?peet",
    re.IGNORECASE,
)
_SEXUAL_VIOLENCE = re.compile(r"\b(sexual\w*|molest\w*|rap(e|ed|ing)|pocso)\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(r"\b(my|our|mera|meri|mere)\b", re.IGNORECASE)
_CHILD_WORDS = re.compile(r"\b(child|children|minor|kid|daughter|sister|brother|boy|girl|\d{1,2}[- ]?year[- ]?old)\b", re.IGNORECASE)
_ABUSE_WORDS = re.compile(r"\b(abus\w*|molest\w*|assault\w*|rap(e|ed|ing)|harass\w*|touch(es|ed|ing)|pocso)\b", re.IGNORECASE)


def detect_harm(text: str) -> Harm | None:
    """Keyword safety net. Runs before any LLM call so it still works when providers are down."""
    if _SELF_HARM.search(text):
        return Harm.SELF_HARM
    if (_FIRST_PERSON.search(text) and _SEXUAL_VIOLENCE.search(text)
            and _CHILD_WORDS.search(text) and _ABUSE_WORDS.search(text)):
        return Harm.CHILD_ABUSE
    if _DOMESTIC_VIOLENCE.search(text):
        return Harm.DOMESTIC_VIOLENCE
    return None


def harm_response(kind: Harm | None) -> str:
    h = HELPLINES
    if kind == Harm.SELF_HARM:
        return (
            "I'm really sorry you're going through this. You don't have to face it alone.\n\n"
            f"• Tele-MANAS (free, 24x7 mental health support): {h['mental_health']}\n"
            f"• If you are in immediate danger, call the emergency number: {h['emergency']}\n\n"
            "Please reach out to someone you trust or one of these services right now. "
            "When you feel able to, I'm here to explain your legal options and rights, "
            f"and free legal aid is available through NALSA ({h['legal_aid']})."
        )
    if kind == Harm.DOMESTIC_VIOLENCE:
        return (
            "I'm sorry this is happening. Your safety comes first.\n\n"
            f"• Immediate danger: call {h['emergency']}\n"
            f"• Women's helpline (24x7): {h['women']}\n\n"
            "In India the Protection of Women from Domestic Violence Act, 2005 lets you ask a magistrate "
            "for protection orders, a right to stay in the shared home, and monetary relief. You can "
            "approach a Protection Officer, the police, or a lawyer, and free legal aid is available "
            f"through NALSA ({h['legal_aid']}). Ask me and I can explain these steps in more detail."
        )
    if kind == Harm.CHILD_ABUSE:
        return (
            "Thank you for speaking up. A child's safety must come first.\n\n"
            f"• Childline (24x7): {h['child']}\n"
            f"• Immediate danger: call {h['emergency']}\n\n"
            "Under the POCSO Act, 2012 anyone who knows of child sexual abuse is legally required to "
            "report it to the police or Childline. Reporting is protected, and the child's identity is "
            "kept confidential. Please report this now. I can explain the process if you'd like."
        )
    return (
        "It sounds like you or someone else may be in danger or distress.\n\n"
        f"• Emergency: {h['emergency']}\n• Women's helpline: {h['women']}\n"
        f"• Childline: {h['child']}\n• Tele-MANAS (mental health): {h['mental_health']}\n\n"
        "Please contact one of these right away. I'm happy to explain the legal side whenever you're ready."
    )


# --- Prompt attacks and untrusted text -------------------------------------------------------
_PROMPT_ATTACK = re.compile(
    r"ignore (all |any )?(your |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)|"
    r"(reveal|show|print|repeat|display|leak)\b.{0,40}\b(system prompt|your (instructions|prompt|rules)|retrieved text)|"
    r"\bjailbreak\b|you are now (an? )?\w+ (with )?no (rules|restrictions)",
    re.IGNORECASE,
)
_DAN = re.compile(r"\bDAN\b")  # case-sensitive on purpose: "Dan" is a common name


def is_prompt_attack(text: str) -> bool:
    return bool(_PROMPT_ATTACK.search(text) or _DAN.search(text))


_DELIMITER_TAGS = re.compile(r"</?\s*(user_message|user_question|retrieved_text|conversation_history)\s*>", re.IGNORECASE)


def delimit(text: str) -> str:
    """Strip our own delimiter tags from untrusted text so it cannot close or fake a data block."""
    return _DELIMITER_TAGS.sub("", text)


# --- Canned responses (no LLM call, no retrieval, never cached) -------------------------------
def out_of_scope_response() -> str:
    return (
        "I can only help with questions about Indian law, such as tenancy, employment, consumer, family, "
        "and criminal matters. I can't help with that topic. If you have an Indian legal question, "
        "please ask it and I'll explain what the law says in plain language."
    )


def decline_response() -> str:
    return (
        "I can't help with that request. I can explain what Indian law says about a situation and "
        "what lawful options exist, but I can't help with hiding evidence, avoiding the police, or "
        "anything else that breaks the law. If you are facing a legal problem, a lawyer can advise "
        f"you confidentially, and free legal aid is available through NALSA ({HELPLINES['legal_aid']})."
    )


def clarify_response() -> str:
    return (
        "I'd be glad to help, but I need a little more detail. What is the situation about? For example: "
        "a landlord or rent issue, a job or salary issue, a consumer complaint, a family matter, or a "
        "police/criminal matter. Tell me what happened in a sentence or two (no need for names or "
        "personal details) and I'll explain what the law says."
    )


def no_sources_response() -> str:
    return (
        "I couldn't find reliable legal sources for that question, so I don't want to guess. "
        "Could you rephrase it or add a little detail, such as the type of dispute and the state? "
        "For anything urgent, please speak to a lawyer. Free legal aid is available through NALSA "
        f"({HELPLINES['legal_aid']})."
    )


def budget_response() -> str:
    return (
        "The service is very busy right now and can't look up new legal sources at the moment. "
        "Please try again later."
    )


# --- Output guardrails ------------------------------------------------------------------------
_LEAK_MARKERS = (
    "AVAILABLE SOURCES", "RETRIEVED TEXT", "How to answer:", "PRIOR CONVERSATION HISTORY",
    "<retrieved_text>", "<user_question>", "<user_message>",
)
_SECTION_RE = re.compile(r"(?i)\b(?:sections?|sec\.?|ss?\.)\s*(\d+[A-Z]{0,2})")
_OUTCOME_RE = re.compile(
    r"(?i)\byou (will|are going to) (definitely |certainly |surely )?win\b|\bguarantee[sd]?\b|"
    r"\byou should (definitely |immediately |simply )?(sue|file|pay|sign|refuse|stop paying)\b"
)
_REPEALED_RE = re.compile(
    r"\b(IPC|Indian Penal Code|CrPC|Cr\.P\.C\.?|Code of Criminal Procedure|Indian Evidence Act)\b"
)
_LABOUR_ACTS_RE = re.compile(
    r"\b(Payment of Wages Act|Minimum Wages Act|Payment of Gratuity Act|Payment of Bonus Act|Equal Remuneration Act|"
    r"Industrial Disputes Act|Industrial Employment \(Standing Orders\) Act|Trade Unions Act|"
    r"Employees' State Insurance Act|Contract Labour \(Regulation and Abolition\) Act)\b",
    re.IGNORECASE,
)
_HIGH_RISK_RE = re.compile(
    r"(?i)\b(arrest\w*|bail|custody|police|fir|detain\w*|jail|prison|chargesheet|summons|warrant|"
    r"anticipatory)\b"
)

REPEALED_NOTE = (
    "Note: the Indian Penal Code, the Code of Criminal Procedure and the Indian Evidence Act were replaced on "
    "1 July 2024 by the Bharatiya Nyaya Sanhita (BNS), the Bharatiya Nagarik Suraksha Sanhita (BNSS) and the "
    "Bharatiya Sakshya Adhiniyam (BSA). Section numbers differ, so please check the current equivalent."
)
OUTCOME_NOTE = (
    "Note: outcomes depend on the facts and the evidence in each case. This is general information, "
    "not a prediction or a recommendation of what you should do."
)
LABOUR_CODE_NOTE = (
    "Note: several central labour laws, including the Payment of Wages Act, the Minimum Wages Act, the Payment "
    "of Gratuity Act and the Industrial Disputes Act, have been consolidated into the Code on Wages, the Code on "
    "Social Security, the Industrial Relations Code and the Occupational Safety, Health and Working Conditions "
    "Code. Please check which provisions are in force today and the Code's equivalent section."
)
WEAK_SOURCES_NOTE = (
    "Note: the sources found for this question may not be the main law on the topic, so this answer may be "
    "incomplete. Please check it with a lawyer."
)
LEGAL_AID_NOTE = (
    "If you are arrested or questioned by the police, you have the right to speak to a lawyer. Free legal aid "
    f"is available through your District Legal Services Authority (NALSA helpline {HELPLINES['legal_aid']})."
)


_CITE_MARK = re.compile(r"\[(\d{1,2})\]")
# Models sometimes write "[3, The Tamil Nadu Act, Section 10(2)]" or "[1, 2]" instead of "[3]" / "[1][2]".
_CITE_COMPOUND = re.compile(r"\[(\d{1,2})((?:\s*[,;]\s*\d{1,2})*)(?:\s*[,;][^\[\]]{0,200})?\]")


def _split_compound(match: re.Match) -> str:
    numbers = [match.group(1)] + re.findall(r"\d{1,2}", match.group(2) or "")
    return "".join(f"[{n}]" for n in numbers)


def process_citations(text: str, source_count: int) -> tuple[str, list[int], list[str]]:
    """Validate the [n] markers an answer uses against the sources it was given.

    Returns (text with invalid markers removed, sorted valid source numbers actually cited, flags).
    A marker that points at a source that does not exist is dropped and flagged `invalid_citation`;
    an answer that cites nothing although sources exist is flagged `no_citations`."""
    flags: list[str] = []
    cited: set[int] = set()
    text = _CITE_COMPOUND.sub(_split_compound, text)

    def keep(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= source_count:
            cited.add(n)
            return match.group(0)
        if "invalid_citation" not in flags:
            flags.append("invalid_citation")
        return ""

    cleaned = _CITE_MARK.sub(keep, text)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)  # tidy gaps left by removed markers
    if source_count and not cited:
        flags.append("no_citations")
    return cleaned, sorted(cited), flags


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60, "ninety": 90,
}
_WORDS = "|".join(_NUMBER_WORDS)
_MONEY_RE = re.compile(
    r"(?:₹|Rs\.?|INR)\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(crore|lakh|thousand))?", re.IGNORECASE
)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|per\s?cent)", re.IGNORECASE)
_DURATION_RE = re.compile(rf"\b(\d{{1,3}}|{_WORDS})[\s-]+(day|week|month|year)s?\b", re.IGNORECASE)


def _digits(token: str) -> str:
    token = token.lower()
    return str(_NUMBER_WORDS[token]) if token in _NUMBER_WORDS else token


def unverified_figures(answer: str, context: str) -> list[str]:
    """Amounts, percentages and time limits in the answer that the retrieved text does not contain.

    These are the figures a model is most likely to invent (court limits, fees, deadlines) and the ones
    a citizen is most likely to act on, so each one must be traceable to a source."""
    ctx = context.lower().replace(",", "")
    ctx_words = re.sub(rf"\b({_WORDS})\b", lambda m: str(_NUMBER_WORDS[m.group(1)]), ctx)
    missing: list[str] = []

    for m in _MONEY_RE.finditer(answer):
        num = m.group(1).replace(",", "")
        unit = (m.group(2) or "").lower()
        pattern = rf"\b{re.escape(num)}\s?{unit}\b" if unit else rf"\b{re.escape(num)}\b"
        if not re.search(pattern, ctx):
            missing.append(m.group(0).strip())
    for m in _PERCENT_RE.finditer(answer):
        if not re.search(rf"\b{re.escape(m.group(1))}\s?(%|per\s?cent)", ctx):
            missing.append(m.group(0).strip())
    for m in _DURATION_RE.finditer(answer):
        n, unit = _digits(m.group(1)), m.group(2).lower()
        if not re.search(rf"\b{re.escape(n)}[\s-]+{unit}s?\b", ctx_words):
            missing.append(m.group(0).strip())
    return list(dict.fromkeys(missing))[:4]


def unverified_sections(answer: str, context: str) -> list[str]:
    """Section numbers the answer names that appear nowhere in the retrieved text."""
    missing = []
    for num in sorted(set(_SECTION_RE.findall(answer))):
        if not re.search(rf"\b{re.escape(num)}\b", context):
            missing.append(num)
    return missing


def apply_output_guardrails(
    answer: str, context: str, question: str, weak_sources: bool = False
) -> tuple[str, list[str]]:
    """Return (answer_with_notes, flags). Notes are appended after the answer body.

    `weak_sources` means the law the question is about could not be found by name, so what was
    retrieved may not be the main law."""
    if any(marker in answer for marker in _LEAK_MARKERS):
        return decline_response(), ["prompt_leak"]

    flags: list[str] = []
    notes: list[str] = []

    if context.strip():
        missing = unverified_sections(answer, context)
        if missing:
            flags.append("unverified_sections")
            listed = ", ".join(f"Section {n}" for n in missing)
            notes.append(
                f"Note: {listed} mentioned above could not be found in the sources retrieved for this answer. "
                "Please verify before relying on it."
            )
        # A figure the person typed themselves ("20% every year") is not something the model made up.
        asked = question.lower().replace(",", "")
        figures = [f for f in unverified_figures(answer, context) if f.lower().replace(",", "") not in asked]
        if figures:
            flags.append("unverified_figures")
            notes.append(
                f"Note: the figure(s) {', '.join(figures)} mentioned above could not be found in the sources "
                "retrieved for this answer. Please verify them before relying on them."
            )
    if _OUTCOME_RE.search(answer):
        flags.append("outcome_language")
        notes.append(OUTCOME_NOTE)
    if _REPEALED_RE.search(answer):
        flags.append("repealed_statute")
        notes.append(REPEALED_NOTE)
    if _LABOUR_ACTS_RE.search(answer) or _LABOUR_ACTS_RE.search(context):
        flags.append("labour_code")
        notes.append(LABOUR_CODE_NOTE)
    if weak_sources:
        flags.append("weak_sources")
        notes.append(WEAK_SOURCES_NOTE)
    if _HIGH_RISK_RE.search(question):
        flags.append("high_risk_topic")
        notes.append(LEGAL_AID_NOTE)

    if notes:
        answer = answer.rstrip() + "\n\n" + "\n\n".join(notes)
    return answer, flags


# --- Rate limiting and call budget (in-memory, per process) -----------------------------------
class RateLimiter:
    """Sliding-window limiter. State is per process: fine for one instance, not for several."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


class DailyBudget:
    """Caps billable external calls per day so a prepaid IKanoon balance can't be drained by abuse.

    The counter lives in the database (usage_counters) so it survives restarts and is shared by
    every server instance. If the database is unreachable it falls back to a per-process counter."""

    def __init__(self, name: str, env_var: str, default: int):
        self.name = name
        self.env_var = env_var
        self.default = default
        self._day = date.today()
        self._used = 0
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        try:
            return int(os.environ.get(self.env_var, self.default))
        except ValueError:
            return self.default

    def consume(self, n: int = 1) -> bool:
        from src import db

        try:
            return db.consume_budget(self.name, n, self.limit)
        except Exception:  # noqa: BLE001
            logger.exception("budget counter unavailable; using in-memory fallback")
        with self._lock:
            today = date.today()
            if today != self._day:
                self._day, self._used = today, 0
            if self._used + n > self.limit:
                return False
            self._used += n
            return True

    def reset(self) -> None:
        from src import db

        with self._lock:
            self._day, self._used = date.today(), 0
        try:
            db.reset_budget(self.name)
        except Exception:  # noqa: BLE001
            logger.exception("could not reset budget counter")


# One IKanoon-backed new question costs about 1 search + up to 5 document fetches.
ikanoon_budget = DailyBudget("ikanoon_calls", "DAILY_IKANOON_CALLS", 1500)
