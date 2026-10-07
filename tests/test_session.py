from datetime import datetime, timedelta, timezone

from src.retrieval.context import Citation
from src.session import Session, SessionStore


def test_session_creation_and_add_message():
    session = Session()
    assert session.session_id is not None
    assert len(session.messages) == 0

    session.add_message("user", "Can my landlord deduct my deposit?")
    session.add_message("assistant", "No, unless stated in the agreement.")

    assert len(session.messages) == 2
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "Can my landlord deduct my deposit?"
    assert session.messages[1].role == "assistant"


def test_session_store_get_or_create():
    store = SessionStore()
    sess1 = store.get_or_create()
    assert sess1.session_id is not None

    sess2 = store.get_or_create(sess1.session_id)
    assert sess2.session_id == sess1.session_id

    # Non-existent ID creates new session
    sess3 = store.get_or_create("non-existent-id")
    assert sess3.session_id != "non-existent-id"


def test_session_store_ttl_expiration():
    store = SessionStore(ttl_seconds=10)
    sess = store.create()
    sess.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=20)
    store.save(sess, update_timestamp=False)

    # Getting an expired session should return None and prune it
    retrieved = store.get(sess.session_id)
    assert retrieved is None

    # cleanup_expired prunes all expired sessions
    sess2 = store.create()
    sess2.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=20)
    store.save(sess2, update_timestamp=False)
    cleaned = store.cleanup_expired()
    assert cleaned >= 1


def test_session_stores_context_and_citations():
    session = Session()
    citation = Citation(
        title="Test Case",
        docsource="Supreme Court",
        publishdate="2020-01-01",
        url="https://indiankanoon.org/doc/123/",
    )
    session.last_context_text = "Relevant legal provisions..."
    session.last_citations = [citation]
    session.last_query = "deposit dispute"

    assert session.last_context_text == "Relevant legal provisions..."
    assert len(session.last_citations) == 1
    assert session.last_citations[0].title == "Test Case"
