from datetime import datetime, timezone
import json
from typing import Optional
import uuid
from pydantic import BaseModel, Field

from src.db import get_db
from src.retrieval.context import Citation


class AnswerWithSession(str):
    session_id: str

    def __new__(cls, content: str, session_id: str):
        obj = super().__new__(cls, content)
        obj.session_id = session_id
        return obj


class Message(BaseModel):
    id: Optional[int] = None
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[Message] = Field(default_factory=list)
    last_context_text: Optional[str] = None
    last_citations: list[Citation] = Field(default_factory=list)
    last_query: Optional[str] = None

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))
        self.last_active_at = datetime.now(timezone.utc)
        if self.title in ("New Chat", "") and role == "user":
            # Auto-title session with first user message
            cleaned_title = content.strip().replace("\n", " ")
            self.title = (
                (cleaned_title[:45] + "...")
                if len(cleaned_title) > 48
                else cleaned_title
            )


class SessionStore:
    MAX_MEMORY_SESSIONS = 200

    def __init__(self, ttl_seconds: int = 86400, db_path: Optional[str] = None):
        self.ttl_seconds = ttl_seconds
        self.db_path = db_path
        # Keep an in-memory cache for speed and test compatibility
        self._memory_sessions: dict[str, Session] = {}

    def _get_conn(self):
        return get_db(self.db_path)

    def get(self, session_id: str) -> Optional[Session]:
        now = datetime.now(timezone.utc)

        # Check memory first
        if session_id in self._memory_sessions:
            sess = self._memory_sessions[session_id]
            if (now - sess.last_active_at).total_seconds() > self.ttl_seconds:
                self._memory_sessions.pop(session_id, None)
                return None
            return sess

        # Check database
        conn = self._get_conn()
        try:
            with conn:
                row = conn.execute(
                    """
                    SELECT session_id, user_id, title, created_at, last_active_at,
                           last_context_text, last_citations, last_query
                    FROM sessions WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()

                if not row:
                    return None

                last_active = datetime.fromisoformat(row["last_active_at"])
                if (now - last_active).total_seconds() > self.ttl_seconds:
                    return None

                # Load messages
                msg_rows = conn.execute(
                    """
                    SELECT id, role, content, timestamp
                    FROM messages WHERE session_id = ?
                    ORDER BY id ASC
                    """,
                    (session_id,),
                ).fetchall()

                messages = [
                    Message(
                        id=m["id"],
                        role=m["role"],
                        content=m["content"],
                        timestamp=datetime.fromisoformat(m["timestamp"]),
                    )
                    for m in msg_rows
                ]

                raw_citations = json.loads(row["last_citations"] or "[]")
                citations = [Citation(**c) for c in raw_citations]

                session = Session(
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    last_active_at=last_active,
                    messages=messages,
                    last_context_text=row["last_context_text"],
                    last_citations=citations,
                    last_query=row["last_query"],
                )
                self._memory_sessions[session.session_id] = session
                return session
        except Exception:
            return None
        finally:
            conn.close()

    def create(
        self, user_id: Optional[str] = None, title: str = "New Chat"
    ) -> Session:
        session = Session(user_id=user_id, title=title)
        self.save(session)
        return session

    def get_or_create(
        self, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Session:
        if session_id:
            session = self.get(session_id)
            if session:
                if user_id and not session.user_id:
                    session.user_id = user_id
                    self.save(session)
                return session
        return self.create(user_id=user_id)

    def save(self, session: Session, update_timestamp: bool = True) -> None:
        if update_timestamp:
            session.last_active_at = datetime.now(timezone.utc)
        self._memory_sessions[session.session_id] = session
        self._evict_if_needed()

        # Persist to DB
        conn = self._get_conn()
        try:
            with conn:
                citations_json = json.dumps(
                    [c.model_dump() for c in session.last_citations]
                )
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, user_id, title, created_at, last_active_at,
                        last_context_text, last_citations, last_query
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        title = excluded.title,
                        last_active_at = excluded.last_active_at,
                        last_context_text = excluded.last_context_text,
                        last_citations = excluded.last_citations,
                        last_query = excluded.last_query
                    """,
                    (
                        session.session_id,
                        session.user_id,
                        session.title,
                        session.created_at.isoformat(),
                        session.last_active_at.isoformat(),
                        session.last_context_text,
                        citations_json,
                        session.last_query,
                    ),
                )

                # Insert any new messages
                for msg in session.messages:
                    if msg.id is None:
                        cursor = conn.execute(
                            """
                            INSERT INTO messages (session_id, role, content, timestamp)
                            VALUES (?, ?, ?, ?)
                            RETURNING id
                            """,
                            (
                                session.session_id,
                                msg.role,
                                msg.content,
                                msg.timestamp.isoformat(),
                            ),
                        )
                        msg.id = cursor.fetchone()["id"]
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                f"Failed to persist session {session.session_id} to database"
            )
        finally:
            conn.close()

    def list_user_sessions(self, user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Fetch sessions belonging to a specific user, sorted newest first, with pagination."""
        conn = self._get_conn()
        try:
            with conn:
                rows = conn.execute(
                    """
                    SELECT session_id, title, created_at, last_active_at
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY last_active_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                ).fetchall()

                return [
                    {
                        "session_id": r["session_id"],
                        "title": r["title"],
                        "created_at": r["created_at"],
                        "last_active_at": r["last_active_at"],
                    }
                    for r in rows
                ]
        finally:
            conn.close()

    def rename_session(self, session_id: str, new_title: str, user_id: str) -> bool:
        """Rename a session if it belongs to the user."""
        cleaned_title = new_title.strip()
        if not cleaned_title:
            return False

        if session_id in self._memory_sessions:
            sess = self._memory_sessions[session_id]
            if sess.user_id == user_id:
                sess.title = cleaned_title

        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE sessions SET title = ? WHERE session_id = ? AND user_id = ?",
                    (cleaned_title, session_id, user_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete a session and its messages if it belongs to the user."""
        self._memory_sessions.pop(session_id, None)

        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM messages WHERE session_id = ? AND session_id IN (SELECT session_id FROM sessions WHERE user_id = ?)",
                    (session_id, user_id),
                )
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                    (session_id, user_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def _evict_if_needed(self) -> None:
        """Evict oldest sessions from in-memory cache when it exceeds MAX_MEMORY_SESSIONS."""
        if len(self._memory_sessions) <= self.MAX_MEMORY_SESSIONS:
            return
        # Sort by last_active_at ascending (oldest first) and remove excess
        sorted_ids = sorted(
            self._memory_sessions,
            key=lambda sid: self._memory_sessions[sid].last_active_at,
        )
        to_remove = len(self._memory_sessions) - self.MAX_MEMORY_SESSIONS
        for sid in sorted_ids[:to_remove]:
            self._memory_sessions.pop(sid, None)

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [
            sid
            for sid, sess in list(self._memory_sessions.items())
            if (now - sess.last_active_at).total_seconds() > self.ttl_seconds
        ]
        for sid in expired:
            self._memory_sessions.pop(sid, None)
        return len(expired)


default_session_store = SessionStore()
