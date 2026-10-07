from fastapi.testclient import TestClient

from src.api import app
from src.auth import create_auth_token
from src.db import init_db
from src.session import SessionStore, default_session_store

client = TestClient(app)


def test_session_store_rename_and_delete(tmp_path):
    db_file = str(tmp_path / "test_mgmt.db")
    init_db(db_file)

    store = SessionStore(db_path=db_file)
    sess = store.create(user_id="user-1", title="Initial Title")
    sess.add_message("user", "Test question")
    store.save(sess)

    # Rename
    assert store.rename_session(sess.session_id, "Updated Legal Topic", "user-1") is True
    loaded = store.get(sess.session_id)
    assert loaded.title == "Updated Legal Topic"

    # Non-owner cannot rename
    assert store.rename_session(sess.session_id, "Hacker Title", "user-2") is False

    # Delete
    assert store.delete_session(sess.session_id, "user-1") is True
    assert store.get(sess.session_id) is None


def test_api_rename_and_delete():
    user_id = "test-user-mgmt"
    email = "mgmt@example.com"
    token = create_auth_token(email, user_id)
    headers = {"Authorization": f"Bearer {token}"}

    sess = default_session_store.create(user_id=user_id, title="Original Question")
    sess.add_message("user", "Hello?")
    default_session_store.save(sess)

    # PATCH rename
    resp_patch = client.patch(
        f"/sessions/{sess.session_id}",
        json={"title": "Renamed Question Title"},
        headers=headers,
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["title"] == "Renamed Question Title"

    # DELETE session
    resp_delete = client.delete(
        f"/sessions/{sess.session_id}",
        headers=headers,
    )
    assert resp_delete.status_code == 200

    # Getting deleted session gives 404
    resp_get = client.get(
        f"/sessions/{sess.session_id}",
        headers=headers,
    )
    assert resp_get.status_code == 404
