"""Background indexing: embed what a cold answer used so later questions can skip IKanoon.

Everything here runs after the user already has their answer. Failures are logged and swallowed: a request
must never fail or slow down because indexing did. Set INDEX_SYNC=1 (tests, scripts) to run inline."""

from concurrent.futures import ThreadPoolExecutor
import logging
import os

from src import store
from src.embeddings import embed_documents

logger = logging.getLogger(__name__)

DUPLICATE_SIMILARITY = 0.97  # a stored question this close is not stored again
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="indexer")


def run_in_background(fn, *args) -> None:
    def safe():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            logger.exception("background indexing failed")

    if os.environ.get("INDEX_SYNC") == "1":
        safe()
    else:
        _pool.submit(safe)


def index_chunks(chunks: list[dict]) -> int:
    """Embed and store the chunks that are not stored yet. Returns how many were added."""
    keys = store.existing_chunk_keys(sorted({c["tid"] for c in chunks}))
    new = [c for c in chunks if (c["tid"], c["idx"]) not in keys]
    if not new:
        return 0
    vectors = embed_documents([c["text"] for c in new])
    store.upsert_chunks([(c["tid"], c["idx"], c["text"], v) for c, v in zip(new, vectors)])
    return len(new)


def index_answer(question: str, question_vector: list[float], answer: str, context_text: str,
                 citations_json: str, chunks: list[dict]) -> None:
    """Store the chunks the answer used (tier 2 material) and the answer itself, unreviewed (tier 1 once reviewed)."""
    if chunks:
        index_chunks(chunks)
    if store.find_similar_answer(question_vector, DUPLICATE_SIMILARITY, reviewed_only=False):
        return
    store.put_answer(question, question_vector, answer, context_text, citations_json, reviewed=False)
