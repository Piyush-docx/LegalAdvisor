from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

DB_PATH = os.environ.get(
    "DATABASE_PATH", str(Path(__file__).parent.parent / "legal.db")
)


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | None = None) -> None:
    conn = get_db(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL,
            last_context_text TEXT,
            last_citations TEXT,
            last_query TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_otps_email ON otps(email);
        
        CREATE TABLE IF NOT EXISTS query_cache (
            search_query TEXT PRIMARY KEY,
            context_text TEXT NOT NULL,
            citations TEXT NOT NULL,
            llm_answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            question TEXT NOT NULL,
            intent TEXT NOT NULL,
            was_cached INTEGER NOT NULL,
            response_time_ms INTEGER NOT NULL
        );
        """)
    conn.close()


def get_cached_query(search_query: str) -> dict | None:
    conn = get_db()
    with conn:
        row = conn.execute(
            "SELECT context_text, citations, llm_answer FROM query_cache WHERE search_query = ?",
            (search_query,)
        ).fetchone()
        if row:
            return dict(row)
    return None


def cache_query(search_query: str, context_text: str, citations: str, llm_answer: str) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO query_cache 
            (search_query, context_text, citations, llm_answer, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                search_query,
                context_text,
                citations,
                llm_answer,
                datetime.now(timezone.utc).isoformat(),
            )
        )


def log_query(question: str, intent: str, was_cached: bool, response_time_ms: int) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT INTO query_logs (timestamp, question, intent, was_cached, response_time_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                question,
                intent,
                1 if was_cached else 0,
                response_time_ms,
            )
        )


def get_admin_logs(limit: int = 100) -> dict[str, Any]:
    conn = get_db()
    with conn:
        total_queries = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
        total_hits = conn.execute("SELECT COUNT(*) FROM query_logs WHERE was_cached = 1").fetchone()[0]
        avg_time = conn.execute("SELECT AVG(response_time_ms) FROM query_logs").fetchone()[0]
        
        logs = conn.execute(
            "SELECT * FROM query_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        
    return {
        "metrics": {
            "total_queries": total_queries,
            "cache_hit_rate": (total_hits / total_queries * 100) if total_queries > 0 else 0.0,
            "avg_response_time_ms": int(avg_time) if avg_time else 0,
        },
        "logs": [dict(log) for log in logs],
    }


# Ensure DB is initialized on module import
init_db()
