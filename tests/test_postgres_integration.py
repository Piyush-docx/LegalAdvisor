"""Runs against the real PostgreSQL in DATABASE_URL inside a throwaway schema, then drops it.

Skipped unless RUN_PG_TESTS=1 (and a postgres DATABASE_URL, from the environment or .env):
    RUN_PG_TESTS=1 python3 -m pytest tests/test_postgres_integration.py -q
It never touches the real tables: every object lives in schema pgtest_<random>.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

if os.environ.get("RUN_PG_TESTS") == "1":
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REAL_URL = os.environ.get("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_TESTS") != "1" or not REAL_URL.startswith(("postgres://", "postgresql://")),
    reason="set RUN_PG_TESTS=1 with a postgres DATABASE_URL to run",
)


@pytest.fixture
def pg(monkeypatch):
    import psycopg

    from src import db

    schema = f"pgtest_{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("DATABASE_URL", REAL_URL)
    monkeypatch.setenv("DB_SCHEMA", schema)
    db.close_pool()
    db.init_db()
    yield db
    db.close_pool()
    with psycopg.connect(db.direct_url(REAL_URL), autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def vec(*head):
    from src.db import EMBEDDING_DIM

    return [*head] + [0.0] * (EMBEDDING_DIM - len(head))


def test_uses_postgres_and_row_access_styles(pg):
    assert pg.using_postgres()
    with pg.transaction() as conn:
        row = conn.execute("SELECT 7 AS n, 'x' AS s").fetchone()
    assert row["n"] == 7 and row[0] == 7 and dict(row) == {"n": 7, "s": "x"}


def test_auth_flow_end_to_end(pg):
    from src import auth

    code = auth.generate_otp("pg@example.com")
    result = auth.verify_otp("pg@example.com", code)

    assert result["user"]["email"] == "pg@example.com"
    assert auth.verify_otp("pg@example.com", code) is None  # single use
    assert auth.verify_auth_token(result["token"])["email"] == "pg@example.com"


def test_sessions_messages_rename_delete(pg):
    from src.session import SessionStore

    store = SessionStore()
    user_id = _user(pg)
    sess = store.create(user_id=user_id)
    sess.add_message("user", "My landlord keeps my deposit")
    sess.add_message("assistant", "Here is the law")
    store.save(sess)
    assert [m.id for m in sess.messages if m.id is None] == []  # RETURNING id populated ids

    fresh = SessionStore()  # no memory cache: must come back from PostgreSQL
    loaded = fresh.get(sess.session_id)
    assert [m.content for m in loaded.messages] == ["My landlord keeps my deposit", "Here is the law"]
    assert fresh.rename_session(sess.session_id, "Deposit dispute", user_id) is True
    assert fresh.list_user_sessions(user_id)[0]["title"] == "Deposit dispute"
    assert fresh.delete_session(sess.session_id, user_id) is True
    assert SessionStore().get(sess.session_id) is None


def _user(pg):
    import uuid as _uuid

    uid = str(_uuid.uuid4())
    with pg.transaction() as conn:
        conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)", (uid, f"{uid}@x.com", "now"))
    return uid


def test_cache_logs_feedback_and_budget(pg):
    pg.cache_query("q", "ctx", json.dumps([]), "answer")
    pg.cache_query("q", "ctx2", json.dumps([]), "answer2")  # upsert
    assert pg.get_cached_query("q")["llm_answer"] == "answer2"

    pg.log_query("question", "NEW_QUERY", False, 120, guardrails="no_sources,pii_redacted")
    pg.save_feedback("down", "q", "a")
    data = pg.get_admin_logs()
    assert data["metrics"]["total_queries"] == 1
    assert data["metrics"]["guardrail_counts"] == {"no_sources": 1, "pii_redacted": 1}
    assert data["metrics"]["feedback"]["down"] == 1

    assert pg.consume_budget("b", 5, 5) is True
    assert pg.consume_budget("b", 1, 5) is False


def test_documents_chunks_vector_search_and_cascade(pg):
    from src import store

    store.upsert_document(1, "NI Act", "Parliament", "1881", 91, "https://indiankanoon.org/doc/1/", "text one")
    store.upsert_document(2, "Rent Act", "Parliament", "1999", 91, "https://indiankanoon.org/doc/2/", "text two")
    store.replace_chunks(1, [("cheque dishonour", vec(1.0, 0.0)), ("notice period", vec(0.0, 1.0))])
    store.replace_chunks(2, [("eviction notice", vec(0.0, 1.0, 1.0))])
    assert store.has_chunks(1) and store.has_chunks(2)

    hits = store.search_chunks(vec(1.0, 0.0), k=2)
    assert hits[0]["text"] == "cheque dishonour" and hits[0]["similarity"] == pytest.approx(1.0, abs=1e-4)
    assert hits[0]["title"] == "NI Act"
    only_doc2 = store.search_chunks(vec(1.0, 0.0), k=5, tids=[2])
    assert {h["tid"] for h in only_doc2} == {2}

    store.upsert_document(1, "NI Act", "Parliament", "1881", 91, "https://indiankanoon.org/doc/1/", "CHANGED")
    assert not store.has_chunks(1)  # changed text invalidates chunks


def test_semantic_answer_cache_threshold_and_reviewed_filter(pg):
    from src import store

    store.put_answer("deposit refund?", vec(1.0, 0.0), "answer A", "ctx", "[]", reviewed=True)
    store.put_answer("evict without notice?", vec(0.0, 1.0), "answer B", "ctx", "[]", reviewed=False)

    near = store.find_similar_answer(vec(1.0, 0.05), min_similarity=0.95)
    assert near["answer"] == "answer A"
    assert store.find_similar_answer(vec(0.5, 0.5), min_similarity=0.95) is None  # too different
    assert store.find_similar_answer(vec(0.0, 1.0), 0.95, reviewed_only=True) is None  # B is unreviewed
    assert store.find_similar_answer(vec(0.0, 1.0), 0.95, reviewed_only=False)["answer"] == "answer B"


# ---------------- embedding model switch (src/embedding_migration.py) ----------------
def _fake_embed(dim):
    def embed(texts, kind):
        # deterministic: first axis encodes text length so results are checkable
        return [[float(len(t))] + [0.0] * (dim - 1) for t in texts]

    return embed


def _switch_model(monkeypatch, model, dim):
    from src import embeddings, store
    import src.db as dbm

    for mod in (embeddings, store):
        monkeypatch.setattr(mod, "EMBEDDING_DIM", dim)
    monkeypatch.setattr(dbm, "EMBEDDING_DIM", dim)
    monkeypatch.setattr(embeddings, "EMBEDDING_MODEL", model)


def test_old_model_vectors_are_invisible_then_reembedded_in_place(pg, monkeypatch):
    from src import embedding_migration as m, store

    store.upsert_document(1, "NI Act", "P", "1881", 91, "https://indiankanoon.org/doc/1/", "text")
    store.replace_chunks(1, [("cheque dishonour", vec(1.0, 0.0))])
    store.put_answer("deposit refund?", vec(1.0, 0.0), "answer", "ctx", "[]", reviewed=True)
    assert store.has_chunks(1)

    _switch_model(monkeypatch, "model-b", 768)  # same size, different model
    assert not store.has_chunks(1)  # old vectors do not count for the new model
    assert store.search_chunks(vec(1.0, 0.0)) == []
    assert store.find_similar_answer(vec(1.0, 0.0), 0.5, reviewed_only=False) is None

    plan = m.make_plan()
    assert plan.stale_rows == {"chunks": 1, "answer_cache": 1} and not plan.needs_dimension_change
    result = m.migrate(embed_texts=_fake_embed(768))

    assert result == {"chunks": 1, "answer_cache": 1, "completed": True}
    assert store.has_chunks(1)
    assert store.search_chunks(vec(1.0, 0.0))[0]["text"] == "cheque dishonour"
    assert m.make_plan().nothing_to_do


def test_vector_size_change_rebuilds_columns_and_indexes(pg, monkeypatch):
    from src import embedding_migration as m, store

    store.upsert_document(1, "NI Act", "P", "1881", 91, "https://indiankanoon.org/doc/1/", "text")
    store.replace_chunks(1, [("cheque dishonour", vec(1.0, 0.0)), ("notice period", vec(0.0, 1.0))])

    _switch_model(monkeypatch, "model-c", 8)  # 768 -> 8 dimensions
    plan = m.make_plan()
    assert plan.needs_dimension_change and plan.column_dims["chunks"] == 768

    result = m.migrate(embed_texts=_fake_embed(8))

    assert result["completed"] and result["chunks"] == 2
    assert m.make_plan().column_dims == {"chunks": 8, "answer_cache": 8}
    hits = store.search_chunks([1.0] + [0.0] * 7, k=2)
    assert len(hits) == 2 and hits[0]["similarity"] == pytest.approx(1.0, abs=1e-4)


def test_migration_stops_cleanly_when_embeddings_unavailable_and_resumes(pg, monkeypatch):
    from src import embedding_migration as m, embeddings, store

    store.upsert_document(1, "NI Act", "P", "1881", 91, "https://indiankanoon.org/doc/1/", "text")
    store.replace_chunks(1, [("a", vec(1.0)), ("b", vec(0.0, 1.0)), ("c", vec(0.0, 0.0, 1.0))])
    _switch_model(monkeypatch, "model-d", 768)
    calls = {"n": 0}

    def flaky(texts, kind):
        calls["n"] += 1
        if calls["n"] == 2:
            raise embeddings.EmbeddingUnavailable("quota")
        return _fake_embed(768)(texts, kind)

    first = m.migrate(batch_size=2, embed_texts=flaky)
    assert first["completed"] is False and first["chunks"] == 2
    assert m.make_plan().stale_rows["chunks"] == 1

    second = m.migrate(batch_size=2, embed_texts=_fake_embed(768))
    assert second["completed"] and second["chunks"] == 1
    assert m.make_plan().nothing_to_do


def test_upsert_chunks_keeps_other_chunks_and_lists_and_reviews_answers(pg):
    from src import store

    store.upsert_document(1, "NI Act", "Parliament", "1881", 91, "https://indiankanoon.org/doc/1/", "text")
    store.upsert_chunks([(1, 0, "first", vec(1.0, 0.0)), (1, 1, "second", vec(0.0, 1.0))])
    store.upsert_chunks([(1, 1, "second v2", vec(0.0, 1.0)), (1, 2, "third", vec(1.0, 1.0))])

    assert store.existing_chunk_keys([1]) == {(1, 0), (1, 1), (1, 2)}
    assert store.existing_chunk_keys([]) == set()
    texts = {h["idx"]: h["text"] for h in store.search_chunks(vec(1.0, 0.0), k=10)}
    assert texts == {0: "first", 1: "second v2", 2: "third"}

    store.put_answer("q one", vec(1.0, 0.0), "a1", "ctx", "[]")
    store.put_answer("q two", vec(0.0, 1.0), "a2", "ctx", "[]", reviewed=True)
    listed = store.list_answers()
    assert [a["question"] for a in listed] == ["q one", "q two"]  # unreviewed first
    assert store.find_similar_answer(vec(1.0, 0.0), 0.9, reviewed_only=True) is None
    assert store.set_answer_reviewed(listed[0]["id"]) is True
    assert store.find_similar_answer(vec(1.0, 0.0), 0.9, reviewed_only=True)["answer"] == "a1"
    assert store.set_answer_reviewed(999999) is False
