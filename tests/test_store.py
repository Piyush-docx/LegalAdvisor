from datetime import datetime, timedelta, timezone

import pytest

from src import db, store


def _doc(tid=1, text="Section 138 text", **kw):
    args = dict(tid=tid, title="NI Act", docsource="Parliament", publishdate="1881-01-01", doctype=91,
                url=f"https://indiankanoon.org/doc/{tid}/", text=text)
    args.update(kw)
    store.upsert_document(**args)


def test_upsert_and_get_fresh_documents():
    _doc(1)
    _doc(2, text="other")

    docs = store.get_fresh_documents([1, 2, 3])

    assert set(docs) == {1, 2}
    assert docs[1]["text"] == "Section 138 text" and docs[1]["url"].endswith("/1/")


def test_upsert_refreshes_existing_document():
    _doc(1, text="old")
    _doc(1, text="new")

    assert store.get_fresh_documents([1])[1]["text"] == "new"


def test_expired_documents_are_not_returned_and_are_purged():
    _doc(1)
    old = (datetime.now(timezone.utc) - timedelta(days=store.DOCUMENT_TTL_DAYS + 1)).isoformat()
    with db.transaction() as conn:
        conn.execute("UPDATE documents SET fetched_at = ? WHERE tid = 1", (old,))
    _doc(2)

    assert set(store.get_fresh_documents([1, 2])) == {2}
    assert store.purge_expired()["documents"] == 1


def test_get_fresh_documents_with_no_ids():
    assert store.get_fresh_documents([]) == {}


def test_vector_storage_requires_postgres_and_says_so():
    with pytest.raises(NotImplementedError):
        store.search_chunks([0.0] * db.EMBEDDING_DIM)
    with pytest.raises(NotImplementedError):
        store.replace_chunks(1, [])


def test_query_cache_entries_expire_after_ttl():
    db.cache_query("q", "ctx", "[]", "answer")
    assert db.get_cached_query("q")["llm_answer"] == "answer"

    old = (datetime.now(timezone.utc) - timedelta(days=db.ANSWER_CACHE_TTL_DAYS + 1)).isoformat()
    with db.transaction() as conn:
        conn.execute("UPDATE query_cache SET created_at = ?", (old,))

    assert db.get_cached_query("q") is None


def test_query_cache_upsert_replaces_answer_and_refreshes_age():
    db.cache_query("q", "ctx1", "[]", "first")
    db.cache_query("q", "ctx2", "[]", "second")

    assert db.get_cached_query("q")["llm_answer"] == "second"


def test_budget_is_atomic_and_persists_in_the_database():
    assert db.consume_budget("t", 6, 10) is True
    assert db.consume_budget("t", 4, 10) is True
    assert db.consume_budget("t", 1, 10) is False  # would exceed
    assert db.consume_budget("t", 11, 10) is False  # single request larger than the limit
    # a new DailyBudget object (as after a restart) sees the same counter
    from src.guardrails import DailyBudget
    import os
    os.environ["PERSIST_TEST"] = "10"
    try:
        assert DailyBudget("t", "PERSIST_TEST", 10).consume(1) is False
    finally:
        del os.environ["PERSIST_TEST"]
    db.reset_budget("t")
    assert db.consume_budget("t", 10, 10) is True


def test_migration_requires_postgres():
    from src import embedding_migration as m

    with pytest.raises(NotImplementedError):
        m.make_plan()
