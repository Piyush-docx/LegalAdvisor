"""Tiers 1 and 2 of the question flow: answer from what is already stored before touching IKanoon.

Tier 1: a reviewed stored answer to a near-identical question (served verbatim).
Tier 2: chunks stored by earlier questions are similar enough to this one (answer is generated from them).
Anything else, or any failure here, means the caller takes the cold path. Nothing in this module may raise."""

import json
import logging
import os
import re

from src import store
from src.db import using_postgres
from src.embeddings import embed_query, is_configured
from src.retrieval.context import Citation, context_from_stored

logger = logging.getLogger(__name__)

TIER1_MIN_SIMILARITY = float(os.environ.get("TIER1_MIN_SIMILARITY", "0.92"))
TIER2_MIN_SIMILARITY = float(os.environ.get("TIER2_MIN_SIMILARITY", "0.62"))
QUESTION_MIN_SIMILARITY = float(os.environ.get("TIER2_QUESTION_SIMILARITY", "0.90"))
TIER2_MIN_CHUNKS = 3
FOLLOWUP_MIN_SIMILARITY = float(os.environ.get("FOLLOWUP_MIN_SIMILARITY", "0.58"))  # live: on-topic 0.59-0.66, other topic 0.56
SEARCH_K = 24  # fetch more than we use so the per-document cap still leaves 8 chunks


def question_vector(question: str, flags: list[str]) -> list[float] | None:
    """Embed the question, or None when vectors are not available (SQLite, no key, quota, outage)."""
    if not using_postgres() or not is_configured():
        return None
    try:
        return embed_query(question)
    except Exception:  # noqa: BLE001
        logger.warning("question embedding unavailable; using the cold path", exc_info=True)
        flags.append("embeddings_unavailable")
        return None


def find_reviewed_answer(vec: list[float]) -> tuple[str, str, list[Citation]] | None:
    """Tier 1: (answer, context_text, citations) of a reviewed stored answer, or None."""
    try:
        hit = store.find_similar_answer(vec, TIER1_MIN_SIMILARITY, reviewed_only=True)
        if not hit:
            return None
        return hit["answer"], hit["context_text"], [Citation(**c) for c in json.loads(hit["citations"])]
    except Exception:  # noqa: BLE001
        logger.exception("tier 1 lookup failed")
        return None


def find_stored_context(vec: list[float]) -> tuple[str, list[Citation], str] | None:
    """Tier 2: (numbered context, citations, kind) built from what is already stored, or None.

    kind "question": a stored question that is nearly the same (any review state): reuse the sources that
    answer used. Question-to-question similarity is far more reliable than question-to-chunk similarity.
    kind "chunks": otherwise the best stored chunks, if similar enough."""
    try:
        similar = store.find_similar_answer(vec, QUESTION_MIN_SIMILARITY, reviewed_only=False)
        if similar:
            return (similar["context_text"], [Citation(**c) for c in json.loads(similar["citations"])], "question")
        rows = store.search_chunks(vec, k=SEARCH_K)
        if not rows or rows[0]["similarity"] < TIER2_MIN_SIMILARITY:
            return None
        rows = [r for r in rows if r["similarity"] >= TIER2_MIN_SIMILARITY]
        if len(rows) < TIER2_MIN_CHUNKS:
            return None
        context_text, citations = context_from_stored(rows)
        return (context_text, citations, "chunks") if context_text.strip() else None
    except Exception:  # noqa: BLE001
        logger.exception("tier 2 lookup failed")
        return None


def find_followup_context(vec: list[float], previous: list[Citation]) -> tuple[str, list[Citation]] | None:
    """E3: context for a follow-up from the stored chunks of the documents the last answer cited.

    Searching only those documents makes a lower bar safe: the follow-up is about the same law."""
    try:
        tids = [int(m.group(1)) for c in previous if (m := re.search(r"/doc/(\d+)", c.url))]
        if not tids:
            return None
        rows = [r for r in store.search_chunks(vec, k=SEARCH_K, tids=tids) if r["similarity"] >= FOLLOWUP_MIN_SIMILARITY]
        if len(rows) < TIER2_MIN_CHUNKS:
            return None
        context_text, citations = context_from_stored(rows)
        return (context_text, citations) if context_text.strip() else None
    except Exception:  # noqa: BLE001
        logger.exception("follow-up lookup failed")
        return None
