from src.db import get_db, init_db
from src.retrieval.context import Citation
from src.session import Session, SessionStore


def test_db_session_persistence(tmp_path):
    db_file = str(tmp_path / "test_sessions.db")
    init_db(db_file)

    store = SessionStore(db_path=db_file)
    session = store.create(user_id="user-xyz", title="Tenant Security Deposit")
    session.add_message("user", "Can my landlord withhold my deposit?")
    session.add_message("assistant", "No, statutory deductions only.")
    session.last_context_text = "Provisions of Tenancy Act Section 14"
    session.last_citations = [
        Citation(
            title="Court Ruling 1",
            docsource="Delhi HC",
            publishdate="2022-01-01",
            url="https://indiankanoon.org/doc/111/",
        )
    ]
    store.save(session)

    # Create a fresh store instance pointing to same DB to test persistence
    fresh_store = SessionStore(db_path=db_file)
    loaded = fresh_store.get(session.session_id)
    assert loaded is not None
    assert loaded.user_id == "user-xyz"
    assert loaded.title == "Tenant Security Deposit"
    assert len(loaded.messages) == 2
    assert loaded.messages[0].content == "Can my landlord withhold my deposit?"
    assert len(loaded.last_citations) == 1
    assert loaded.last_citations[0].title == "Court Ruling 1"

    # List user sessions
    user_sessions = fresh_store.list_user_sessions("user-xyz")
    assert len(user_sessions) == 1
    assert user_sessions[0]["session_id"] == session.session_id
    assert user_sessions[0]["title"] == "Tenant Security Deposit"
