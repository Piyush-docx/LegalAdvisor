"""Database access: PostgreSQL in production, SQLite for tests and local development.

The backend is chosen per call:
  * ``get_db(path)`` with an explicit path           -> SQLite (tests pass a temp file)
  * ``get_db()`` with ``DATABASE_URL=postgres...``    -> PostgreSQL through a connection pool
  * ``get_db()`` otherwise                            -> SQLite at ``DATABASE_PATH``

Callers write SQLite-style SQL (``?`` placeholders, ``with conn:`` transactions, ``row["col"]``);
the PostgreSQL wrapper translates, so auth.py and session.py need no backend branches.
Vector tables (chunks, answer_cache) exist on PostgreSQL only.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "DATABASE_PATH", str(Path(__file__).parent.parent / "legal.db")
)

# Vector size of the embedding model in use (Gemini embeddings can be truncated to this; pgvector HNSW
# indexes support up to 2000). Changing it needs a column migration: see docs/embedding_model_switch.md.
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
ANSWER_CACHE_TTL_DAYS = int(os.environ.get("ANSWER_CACHE_TTL_DAYS", "30"))


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url if url.startswith(("postgres://", "postgresql://")) else None


def using_postgres(db_path: str | None = None) -> bool:
    return db_path is None and database_url() is not None


def direct_url(url: str) -> str:
    """Neon's pooled hostname contains '-pooler'; DDL and session settings want the direct one."""
    return re.sub(r"-pooler(?=\.)", "", url, count=1)


# ----------------------------------------------------------------------------------------------
# PostgreSQL plumbing
# ----------------------------------------------------------------------------------------------
class Row(dict):
    """Dict row that also supports positional access, like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    columns = [c.name for c in cursor.description] if cursor.description else []

    def make(values):
        return Row(zip(columns, values))

    return make


def _db_schema() -> str | None:
    schema = os.environ.get("DB_SCHEMA", "").strip()
    return schema if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema) else None


def _configure(conn) -> None:
    """Runs on every new pooled connection. Must leave it idle (no open transaction)."""
    schema = _db_schema()
    if schema:
        conn.execute(f'SET search_path TO "{schema}", public')
        conn.commit()  # SET is transactional until committed
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except Exception:  # noqa: BLE001 - the vector type does not exist until init_db has run
        pass
    finally:
        conn.rollback()


_pool = None
_pool_url = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool, _pool_url
    url = database_url()
    with _pool_lock:
        if _pool is None or _pool_url != url:
            from psycopg_pool import ConnectionPool

            if _pool is not None:
                _pool.close()
            use = direct_url(url) if _db_schema() else url
            _pool = ConnectionPool(
                use,
                min_size=1,
                max_size=int(os.environ.get("DB_POOL_MAX", "10")),
                kwargs={"row_factory": _row_factory, "prepare_threshold": None, "connect_timeout": 20},
                configure=_configure,
                # No per-checkout health check (it costs a round trip on every call). Instead idle
                # connections are recycled before Neon suspends them, and _PgConnection retries once
                # if a stale one still slips through.
                max_idle=120,
                max_lifetime=1800,
                timeout=30,
                open=False,
            )
            _pool.open(wait=False)
            _pool_url = url
        return _pool


def close_pool() -> None:
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


def _to_pg(sql: str, has_params: bool) -> str:
    # The app's SQL uses SQLite '?' placeholders and contains no literal '?' or '%'.
    return sql.replace("%", "%%").replace("?", "%s") if has_params else sql


class _PgConnection:
    """sqlite3-shaped wrapper over a pooled psycopg connection.

    The pooled connection is taken lazily and handed back on ``close()`` and at the end of every
    ``with conn:`` block, so call sites that forget ``close()`` cannot exhaust the pool."""

    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        self._used = False  # has this checkout run a statement yet?

    def _acquire(self):
        if self._conn is None:
            last: Exception | None = None
            for attempt in range(3):  # Neon scales to zero; the first connection may need to wake it
                try:
                    self._conn = self._pool.getconn()
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(1 + attempt)
            if self._conn is None:
                raise last  # type: ignore[misc]
        return self._conn

    def execute(self, sql: str, params=()):
        import psycopg

        params = tuple(params) if params else None
        query = _to_pg(sql, params is not None)
        try:
            cursor = self._acquire().execute(query, params)
        except psycopg.OperationalError:
            if self._used:
                raise  # mid-transaction failure: do not silently replay half a transaction
            # Stale connection from the pool (e.g. Neon suspended it): drop it and try once more.
            bad, self._conn = self._conn, None
            if bad is not None:
                self._pool.putconn(bad)
            cursor = self._acquire().execute(query, params)
        self._used = True
        return cursor

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def rollback(self) -> None:
        if self._conn is not None:
            self._conn.rollback()

    def close(self) -> None:
        if self._conn is not None:
            conn, self._conn = self._conn, None
            self._pool.putconn(conn)  # the pool rolls back anything uncommitted
        self._used = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._conn is not None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        self.close()
        return False


def get_db(db_path: str | None = None):
    if using_postgres(db_path):
        return _PgConnection(_get_pool())
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(db_path: str | None = None):
    """One transaction on a fresh connection that is always returned/closed afterwards."""
    conn = get_db(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ----------------------------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------------------------
def _schema_statements(postgres: bool) -> list[str]:
    pk = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS otps (
            id {pk},
            email TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL,
            last_context_text TEXT,
            last_citations TEXT,
            last_query TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS messages (
            id {pk},
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_otps_email ON otps(email)",
        """CREATE TABLE IF NOT EXISTS query_cache (
            search_query TEXT PRIMARY KEY,
            context_text TEXT NOT NULL,
            citations TEXT NOT NULL,
            llm_answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS query_logs (
            id {pk},
            timestamp TEXT NOT NULL,
            question TEXT NOT NULL,
            intent TEXT NOT NULL,
            was_cached INTEGER NOT NULL,
            response_time_ms INTEGER NOT NULL,
            guardrails TEXT NOT NULL DEFAULT ''
        )""",
        f"""CREATE TABLE IF NOT EXISTS feedback (
            id {pk},
            created_at TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            rating TEXT NOT NULL,
            question TEXT NOT NULL,
            answer_excerpt TEXT NOT NULL,
            comment TEXT
        )""",
        # Per-day counters (e.g. the IKanoon call budget) that survive restarts.
        """CREATE TABLE IF NOT EXISTS usage_counters (
            day TEXT NOT NULL,
            name TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (day, name)
        )""",
        # Retrieved IKanoon documents kept for retrieval (see docs/phase_3_postgres_walkthrough.md).
        """CREATE TABLE IF NOT EXISTS documents (
            tid BIGINT PRIMARY KEY,
            title TEXT NOT NULL,
            docsource TEXT NOT NULL,
            publishdate TEXT NOT NULL,
            doctype INTEGER,
            url TEXT NOT NULL,
            text TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )""",
    ]
    if postgres:
        statements += [
            f"""CREATE TABLE IF NOT EXISTS chunks (
                id BIGSERIAL PRIMARY KEY,
                tid BIGINT NOT NULL REFERENCES documents (tid) ON DELETE CASCADE,
                idx INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding vector({EMBEDDING_DIM}) NOT NULL,
                embedding_model TEXT NOT NULL DEFAULT '',
                UNIQUE (tid, idx)
            )""",
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)",
            f"""CREATE TABLE IF NOT EXISTS answer_cache (
                id BIGSERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                question_embedding vector({EMBEDDING_DIM}) NOT NULL,
                answer TEXT NOT NULL,
                context_text TEXT NOT NULL,
                citations TEXT NOT NULL,
                reviewed BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TEXT NOT NULL,
                embedding_model TEXT NOT NULL DEFAULT ''
            )""",
            "ALTER TABLE answer_cache ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_answer_cache_embedding ON answer_cache USING hnsw (question_embedding vector_cosine_ops)",
        ]
    return statements


VECTOR_INDEXES = {
    "idx_chunks_embedding": "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)",
    "idx_answer_cache_embedding": "CREATE INDEX IF NOT EXISTS idx_answer_cache_embedding ON answer_cache USING hnsw (question_embedding vector_cosine_ops)",
}


def init_db(db_path: str | None = None) -> None:
    if using_postgres(db_path):
        import psycopg

        # DDL goes through the direct (non-pooled) endpoint: poolers dislike session-level setup.
        with psycopg.connect(direct_url(database_url()), autocommit=True, connect_timeout=30) as conn:
            schema = _db_schema()
            if schema:
                conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                conn.execute(f'SET search_path TO "{schema}", public')
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            for statement in _schema_statements(postgres=True):
                conn.execute(statement)
        return

    conn = get_db(db_path)
    with conn:
        for statement in _schema_statements(postgres=False):
            conn.execute(statement)
        # Databases created before Phase 1 lack the guardrails column.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(query_logs)")}
        if "guardrails" not in columns:
            conn.execute("ALTER TABLE query_logs ADD COLUMN guardrails TEXT NOT NULL DEFAULT ''")
    conn.close()


# ----------------------------------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------------------------------
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_cached_query(search_query: str) -> dict | None:
    """Return a cached answer unless it is older than ANSWER_CACHE_TTL_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ANSWER_CACHE_TTL_DAYS)).isoformat()
    with transaction() as conn:
        row = conn.execute(
            "SELECT context_text, citations, llm_answer FROM query_cache "
            "WHERE search_query = ? AND created_at >= ?",
            (search_query, cutoff),
        ).fetchone()
    return dict(row) if row else None


def cache_query(search_query: str, context_text: str, citations: str, llm_answer: str) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO query_cache (search_query, context_text, citations, llm_answer, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (search_query) DO UPDATE SET
                context_text = excluded.context_text,
                citations = excluded.citations,
                llm_answer = excluded.llm_answer,
                created_at = excluded.created_at
            """,
            (search_query, context_text, citations, llm_answer, _iso_now()),
        )


def log_query(
    question: str, intent: str, was_cached: bool, response_time_ms: int, guardrails: str = ""
) -> None:
    """`question` must already be PII-redacted; `guardrails` is a comma-separated list of triggered flags."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO query_logs (timestamp, question, intent, was_cached, response_time_ms, guardrails)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_iso_now(), question, intent, 1 if was_cached else 0, response_time_ms, guardrails),
        )


def save_feedback(
    rating: str, question: str, answer_excerpt: str, session_id: str | None = None,
    user_id: str | None = None, comment: str | None = None,
) -> None:
    """Text fields must already be PII-redacted."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO feedback (created_at, session_id, user_id, rating, question, answer_excerpt, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_iso_now(), session_id, user_id, rating, question, answer_excerpt, comment),
        )


def consume_budget(name: str, amount: int, limit: int) -> bool:
    """Atomically add `amount` to today's counter unless that would exceed `limit`."""
    if amount > limit:
        return False
    day = datetime.now(timezone.utc).date().isoformat()
    with transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO usage_counters (day, name, count) VALUES (?, ?, ?)
            ON CONFLICT (day, name) DO UPDATE SET count = usage_counters.count + excluded.count
            WHERE usage_counters.count + excluded.count <= ?
            RETURNING count
            """,
            (day, name, amount, limit),
        ).fetchone()
    return row is not None


def reset_budget(name: str) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    with transaction() as conn:
        conn.execute("DELETE FROM usage_counters WHERE day = ? AND name = ?", (day, name))


def get_admin_logs(limit: int = 100) -> dict[str, Any]:
    with transaction() as conn:
        total_queries = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
        total_hits = conn.execute("SELECT COUNT(*) FROM query_logs WHERE was_cached = 1").fetchone()[0]
        avg_time = conn.execute("SELECT AVG(response_time_ms) FROM query_logs").fetchone()[0]

        logs = conn.execute(
            "SELECT * FROM query_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        flag_rows = conn.execute("SELECT guardrails FROM query_logs WHERE guardrails != ''").fetchall()
        fb = {r["rating"]: r["n"] for r in conn.execute("SELECT rating, COUNT(*) AS n FROM feedback GROUP BY rating")}
        downvotes = conn.execute(
            "SELECT created_at, question, answer_excerpt, comment FROM feedback WHERE rating = 'down' "
            "ORDER BY id DESC LIMIT 20"
        ).fetchall()

    guardrail_counts: dict[str, int] = {}
    for row in flag_rows:
        for flag in row["guardrails"].split(","):
            if flag:
                guardrail_counts[flag] = guardrail_counts.get(flag, 0) + 1

    return {
        "metrics": {
            "total_queries": total_queries,
            "cache_hit_rate": (total_hits / total_queries * 100) if total_queries > 0 else 0.0,
            "avg_response_time_ms": int(avg_time) if avg_time else 0,
            "guardrail_counts": dict(sorted(guardrail_counts.items(), key=lambda kv: -kv[1])),
            "feedback": {"up": fb.get("up", 0), "down": fb.get("down", 0)},
        },
        "logs": [dict(log) for log in logs],
        "recent_downvotes": [dict(r) for r in downvotes],
    }


# Ensure DB is initialized on module import
init_db()
