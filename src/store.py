"""Storage for retrieved IKanoon documents, their embedded chunks, and the semantic answer cache.

Built in Phase 3 and consumed by the Phase 4 retrieval redesign. Documents work on both backends;
chunk and answer-cache vectors need PostgreSQL with pgvector (DATABASE_URL).

Only what retrieval needs is stored, with expiry (DOCUMENT_TTL_DAYS, ANSWER_CACHE_TTL_DAYS), and
stored full text is never sent to users. Attribution to IKanoon stays on every answer.
"""

from datetime import datetime, timedelta, timezone
import os

from src.db import ANSWER_CACHE_TTL_DAYS, EMBEDDING_DIM, transaction, using_postgres
from src.embeddings import embedding_id

DOCUMENT_TTL_DAYS = int(os.environ.get("DOCUMENT_TTL_DAYS", "90"))


def _iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _require_postgres() -> None:
    if not using_postgres():
        raise NotImplementedError("vector storage needs DATABASE_URL (PostgreSQL with pgvector)")


def _vector(embedding: list[float]):
    from pgvector import Vector

    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"embedding has {len(embedding)} dimensions, expected {EMBEDDING_DIM}")
    return Vector(embedding)


# ---------------------------------------------------------------- documents (both backends)
def upsert_document(
    tid: int, title: str, docsource: str, publishdate: str, doctype: int | None, url: str, text: str
) -> None:
    """Insert or refresh a document. Changed text invalidates its chunks (they are re-embedded)."""
    with transaction() as conn:
        existing = conn.execute("SELECT text FROM documents WHERE tid = ?", (tid,)).fetchone()
        conn.execute(
            """
            INSERT INTO documents (tid, title, docsource, publishdate, doctype, url, text, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tid) DO UPDATE SET
                title = excluded.title, docsource = excluded.docsource, publishdate = excluded.publishdate,
                doctype = excluded.doctype, url = excluded.url, text = excluded.text,
                fetched_at = excluded.fetched_at
            """,
            (tid, title, docsource, publishdate, doctype, url, text, _iso()),
        )
        if existing and existing["text"] != text and using_postgres():
            conn.execute("DELETE FROM chunks WHERE tid = ?", (tid,))


def get_fresh_documents(tids: list[int]) -> dict[int, dict]:
    """Stored documents younger than DOCUMENT_TTL_DAYS, keyed by tid."""
    if not tids:
        return {}
    marks = ", ".join("?" for _ in tids)
    with transaction() as conn:
        rows = conn.execute(
            f"SELECT * FROM documents WHERE tid IN ({marks}) AND fetched_at >= ?",
            (*tids, _iso(DOCUMENT_TTL_DAYS)),
        ).fetchall()
    return {int(r["tid"]): dict(r) for r in rows}


# ---------------------------------------------------------------- chunks (PostgreSQL)
def replace_chunks(tid: int, chunks: list[tuple[str, list[float]]]) -> None:
    """Replace a document's chunks. `chunks` is a list of (text, embedding) from the CURRENT embedding model."""
    _require_postgres()
    with transaction() as conn:
        conn.execute("DELETE FROM chunks WHERE tid = ?", (tid,))
        for idx, (text, embedding) in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (tid, idx, text, embedding, embedding_model) VALUES (?, ?, ?, ?, ?)",
                (tid, idx, text, _vector(embedding), embedding_id()),
            )


def upsert_chunks(chunks: list[tuple[int, int, str, list[float]]]) -> None:
    """Add or refresh chunks given as (tid, idx, text, embedding) without touching a document's other chunks."""
    _require_postgres()
    with transaction() as conn:
        for tid, idx, text, embedding in chunks:
            conn.execute(
                """
                INSERT INTO chunks (tid, idx, text, embedding, embedding_model) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tid, idx) DO UPDATE SET
                    text = excluded.text, embedding = excluded.embedding, embedding_model = excluded.embedding_model
                """,
                (tid, idx, text, _vector(embedding), embedding_id()),
            )


def existing_chunk_keys(tids: list[int]) -> set[tuple[int, int]]:
    """(tid, idx) pairs already embedded by the current model, so they are not embedded twice."""
    _require_postgres()
    if not tids:
        return set()
    marks = ", ".join("?" for _ in tids)
    with transaction() as conn:
        rows = conn.execute(
            f"SELECT tid, idx FROM chunks WHERE embedding_model = ? AND tid IN ({marks})", (embedding_id(), *tids)
        ).fetchall()
    return {(int(r["tid"]), int(r["idx"])) for r in rows}


def has_chunks(tid: int) -> bool:
    """True if the document has chunks made by the current embedding model."""
    _require_postgres()
    with transaction() as conn:
        return conn.execute(
            "SELECT 1 FROM chunks WHERE tid = ? AND embedding_model = ? LIMIT 1", (tid, embedding_id())
        ).fetchone() is not None


def search_chunks(embedding: list[float], k: int = 8, tids: list[int] | None = None) -> list[dict]:
    """Nearest chunks by cosine similarity (1.0 = identical), optionally limited to some documents."""
    _require_postgres()
    vec = _vector(embedding)
    # Only compare against vectors from the same embedding model; others live in a different space.
    where, params = "WHERE c.embedding_model = ?", [vec, embedding_id()]
    if tids:
        where += f" AND c.tid IN ({', '.join('?' for _ in tids)})"
        params += list(tids)
    params += [vec, k]
    with transaction() as conn:
        rows = conn.execute(
            f"""
            SELECT c.tid, c.idx, c.text, d.title, d.docsource, d.publishdate, d.url,
                   1 - (c.embedding <=> ?) AS similarity
            FROM chunks c JOIN documents d ON d.tid = c.tid
            {where}
            ORDER BY c.embedding <=> ? LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- semantic answer cache (PostgreSQL)
def put_answer(
    question: str, embedding: list[float], answer: str, context_text: str, citations_json: str,
    reviewed: bool = False,
) -> None:
    _require_postgres()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO answer_cache
                (question, question_embedding, answer, context_text, citations, reviewed, created_at, embedding_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (question, _vector(embedding), answer, context_text, citations_json, reviewed, _iso(), embedding_id()),
        )


def find_similar_answer(
    embedding: list[float], min_similarity: float, reviewed_only: bool = True
) -> dict | None:
    """Closest cached answer at or above `min_similarity`. Legal questions that differ by one word
    can have opposite answers, so keep the threshold high and prefer reviewed answers."""
    _require_postgres()
    vec = _vector(embedding)
    extra = "AND reviewed = TRUE" if reviewed_only else ""
    with transaction() as conn:
        row = conn.execute(
            f"""
            SELECT id, question, answer, context_text, citations, reviewed,
                   1 - (question_embedding <=> ?) AS similarity
            FROM answer_cache
            WHERE created_at >= ? AND embedding_model = ? {extra}
            ORDER BY question_embedding <=> ? LIMIT 1
            """,
            (vec, _iso(ANSWER_CACHE_TTL_DAYS), embedding_id(), vec),
        ).fetchone()
    if row and row["similarity"] >= min_similarity:
        return dict(row)
    return None


def list_answers(limit: int = 100, reviewed: bool | None = None) -> list[dict]:
    """Stored answers for the admin review screen, unreviewed first, newest first."""
    _require_postgres()
    where, params = "", []
    if reviewed is not None:
        where, params = "WHERE reviewed = ?", [reviewed]
    with transaction() as conn:
        rows = conn.execute(
            f"SELECT id, question, answer, citations, reviewed, created_at FROM answer_cache {where} "
            "ORDER BY reviewed ASC, created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def set_answer_reviewed(answer_id: int, reviewed: bool = True) -> bool:
    """Promote (or demote) a stored answer for verbatim serving. False if there is no such answer."""
    _require_postgres()
    with transaction() as conn:
        return conn.execute("UPDATE answer_cache SET reviewed = ? WHERE id = ?", (reviewed, answer_id)).rowcount > 0


def purge_expired() -> dict[str, int]:
    """Delete expired documents (their chunks cascade) and answer-cache rows; returns counts."""
    counts = {}
    with transaction() as conn:
        counts["documents"] = conn.execute(
            "DELETE FROM documents WHERE fetched_at < ?", (_iso(DOCUMENT_TTL_DAYS),)
        ).rowcount
        if using_postgres():
            counts["answer_cache"] = conn.execute(
                "DELETE FROM answer_cache WHERE created_at < ?", (_iso(ANSWER_CACHE_TTL_DAYS),)
            ).rowcount
    return counts
