"""E2: tiers 1-2 (stored answers and chunks) and background indexing, with store/embeddings patched."""

import json
from unittest.mock import patch

import pytest

from src import pipeline
from src.embeddings import EmbeddingUnavailable
from src.retrieval import indexer, tiers
from src.retrieval.context import Citation, context_from_stored
from src.session import SessionStore
from tests.helpers import llm_result

CIT = {"title": "Section 15 in The Payment Of Wages Act, 1936", "docsource": "Union of India - Section",
       "publishdate": "1936-01-01", "url": "https://indiankanoon.org/doc/7/"}
VEC = [1.0, 0.0]


def row(tid, idx, text="chunk", sim=0.8, title="Act A"):
    return {"tid": tid, "idx": idx, "text": text, "title": title, "docsource": "Union", "publishdate": "1936",
            "url": f"https://indiankanoon.org/doc/{tid}/", "similarity": sim}


@pytest.fixture(autouse=True)
def sync_indexing(monkeypatch):
    monkeypatch.setenv("INDEX_SYNC", "1")


@pytest.fixture
def pg_mode(monkeypatch):
    """Pretend PostgreSQL + embeddings exist; the store functions are patched per test."""
    monkeypatch.setattr(tiers, "using_postgres", lambda: True)
    monkeypatch.setattr(pipeline, "using_postgres", lambda: True)
    monkeypatch.setattr(tiers, "is_configured", lambda: True)
    monkeypatch.setattr(tiers, "embed_query", lambda q: VEC)


def ask(q="can my employer withhold my salary?"):
    return pipeline.answer_question(q, session_store=SessionStore(), return_session=True)[0]


# ------------------------------------------------------------------ context_from_stored
def test_context_from_stored_caps_per_document_and_numbers_in_order():
    rows = [row(1, i, f"a{i}", 0.9 - i * 0.01) for i in range(5)] + [row(2, 0, "b0", 0.7, "Act B")]

    text, cits = context_from_stored(rows, max_chunks=8, per_doc_cap=3)

    assert [c.title for c in cits] == ["Act A", "Act B"]
    assert text.count("- a") == 3 and "a3" not in text and "- b0" in text
    assert text.startswith("[1] Act A") and "[2] Act B" in text


# ------------------------------------------------------------------ tiers
def test_no_vector_on_sqlite_and_flags_nothing():
    flags: list[str] = []
    assert tiers.question_vector("q", flags) is None and flags == []


def test_embedding_failure_flags_and_returns_none(pg_mode, monkeypatch):
    def boom(q):
        raise EmbeddingUnavailable("quota")

    monkeypatch.setattr(tiers, "embed_query", boom)
    flags: list[str] = []
    assert tiers.question_vector("q", flags) is None and flags == ["embeddings_unavailable"]


def test_tier2_reuses_sources_of_a_similar_stored_question(monkeypatch):
    hit = {"context_text": "[1] Act\n- text", "citations": json.dumps([CIT])}
    seen = {}
    monkeypatch.setattr(tiers.store, "find_similar_answer",
                        lambda v, m, reviewed_only=True: seen.update(m=m, r=reviewed_only) or hit)

    context, cits, kind = tiers.find_stored_context(VEC)

    assert kind == "question" and cits[0].title == CIT["title"]
    assert seen == {"m": tiers.QUESTION_MIN_SIMILARITY, "r": False}  # unreviewed is fine: we regenerate


def test_tier2_needs_similarity_and_enough_chunks(monkeypatch):
    monkeypatch.setattr(tiers.store, "find_similar_answer", lambda *a, **k: None)
    rows = [row(1, 0, sim=0.8), row(1, 1, sim=0.75), row(2, 0, sim=0.71)]
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: rows)
    assert tiers.find_stored_context(VEC) is not None

    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: rows[:2])
    assert tiers.find_stored_context(VEC) is None  # only 2 chunks

    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: [row(1, i, sim=0.6) for i in range(4)])
    assert tiers.find_stored_context(VEC) is None  # best match below the bar


def test_tier_lookup_errors_fall_through(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(tiers.store, "find_similar_answer", boom)
    monkeypatch.setattr(tiers.store, "search_chunks", boom)
    assert tiers.find_reviewed_answer(VEC) is None and tiers.find_stored_context(VEC) is None


# ------------------------------------------------------------------ pipeline
@patch("src.pipeline.rewrite_query")
@patch("src.generation.generate.complete")
def test_tier1_serves_reviewed_answer_without_llm_or_ikanoon(mock_complete, mock_rewrite, pg_mode, monkeypatch):
    hit = {"answer": "Stored answer [1].", "context_text": "[1] Act\n- text", "citations": json.dumps([CIT])}
    monkeypatch.setattr(tiers.store, "find_similar_answer", lambda v, m, reviewed_only=True: hit)

    answer = ask()

    assert "Stored answer" in answer and "indiankanoon.org/doc/7" in answer
    mock_complete.assert_not_called()
    mock_rewrite.assert_not_called()


@patch("src.pipeline.rewrite_query")
@patch("src.generation.generate.complete")
def test_tier2_generates_from_stored_chunks_and_stores_answer(mock_complete, mock_rewrite, pg_mode, monkeypatch):
    monkeypatch.setattr(tiers.store, "find_similar_answer", lambda *a, **k: None)
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: [row(1, i, f"text {i}") for i in range(3)])
    mock_complete.return_value = llm_result("Employers must pay wages on time [1].")
    saved = []
    monkeypatch.setattr(indexer.store, "find_similar_answer", lambda *a, **k: None)
    monkeypatch.setattr(indexer.store, "put_answer", lambda *a, **k: saved.append(a))

    answer = ask()

    assert "wages on time" in answer
    mock_rewrite.assert_not_called()  # no rewrite, so no IKanoon either
    assert len(saved) == 1 and saved[0][0].startswith("can my employer")


@patch("src.pipeline.build_context")
@patch("src.pipeline.rewrite_query", return_value='"Payment of Wages Act, 1936" doctypes:laws')
@patch("src.generation.generate.complete")
def test_cold_path_indexes_chunks_and_answer(mock_complete, mock_rewrite, mock_build, pg_mode, monkeypatch):
    chunks = [{"tid": 7, "idx": 0, "text": "Wages shall be paid"}, {"tid": 7, "idx": 1, "text": "Deductions"}]

    def fake_build(q, question=None, consume=None, info=None):
        info.update(act_requested=True, act_matched=True, chunks=chunks)
        return "[1] Act\n- Wages shall be paid", [Citation(**CIT)]

    mock_build.side_effect = fake_build
    mock_complete.return_value = llm_result("Wages must be paid [1].")
    monkeypatch.setattr(tiers.store, "find_similar_answer", lambda *a, **k: None)
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: [])
    monkeypatch.setattr(indexer.store, "find_similar_answer", lambda *a, **k: None)
    monkeypatch.setattr(indexer.store, "existing_chunk_keys", lambda tids: {(7, 1)})  # idx 1 already stored
    embedded, stored_chunks, saved = [], [], []
    monkeypatch.setattr(indexer, "embed_documents", lambda texts: embedded.extend(texts) or [VEC] * len(texts))
    monkeypatch.setattr(indexer.store, "upsert_chunks", lambda c: stored_chunks.extend(c))
    monkeypatch.setattr(indexer.store, "put_answer", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(pipeline, "cache_query", lambda *a: None)

    ask()

    assert embedded == ["Wages shall be paid"]  # only the missing chunk costs embedding quota
    assert [(t, i) for t, i, _, _ in stored_chunks] == [(7, 0)]
    assert len(saved) == 1


@patch("src.pipeline.build_context")
@patch("src.pipeline.rewrite_query", return_value='"Some Act, 1990" doctypes:laws')
@patch("src.generation.generate.complete")
def test_weak_sources_are_not_indexed(mock_complete, mock_rewrite, mock_build, pg_mode, monkeypatch):
    def fake_build(q, question=None, consume=None, info=None):
        info.update(act_requested=True, act_matched=False, chunks=[{"tid": 1, "idx": 0, "text": "x"}])
        return "[1] Act\n- x", [Citation(**CIT)]

    mock_build.side_effect = fake_build
    mock_complete.return_value = llm_result("Answer [1].")
    monkeypatch.setattr(tiers.store, "find_similar_answer", lambda *a, **k: None)
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k: [])
    monkeypatch.setattr(pipeline, "cache_query", lambda *a: None)
    called = []
    monkeypatch.setattr(pipeline, "index_answer", lambda *a: called.append(a))

    ask()

    assert called == []


@patch("src.pipeline.rewrite_query", side_effect=lambda q, **kw: q)
@patch("src.generation.generate.complete")
def test_embeddings_down_still_answers_through_cold_path(mock_complete, mock_rewrite, pg_mode, monkeypatch):
    def boom(q):
        raise EmbeddingUnavailable("quota")

    monkeypatch.setattr(tiers, "embed_query", boom)
    monkeypatch.setattr(pipeline, "_retrieve", lambda q, question, flags, info=None: ("[1] A\n- t", [Citation(**CIT)], None, False))
    monkeypatch.setattr(pipeline, "cache_query", lambda *a: None)
    mock_complete.return_value = llm_result("Fine [1].")

    assert "Fine" in ask()


def test_indexer_never_raises(monkeypatch):
    def boom(*a):
        raise RuntimeError("neon down")

    monkeypatch.setattr(indexer, "index_answer", boom)
    indexer.run_in_background(indexer.index_answer, 1)  # must not raise


def test_indexer_skips_near_duplicate_questions(monkeypatch):
    monkeypatch.setattr(indexer.store, "find_similar_answer", lambda *a, **k: {"id": 1})
    saved = []
    monkeypatch.setattr(indexer.store, "put_answer", lambda *a, **k: saved.append(a))

    indexer.index_answer("q", VEC, "a", "ctx", "[]", [])

    assert saved == []


# ------------------------------------------------------------------ admin endpoints
def test_admin_answer_endpoints_need_postgres_and_admin():
    from fastapi.testclient import TestClient

    from src.api import app

    client = TestClient(app)
    assert client.get("/admin/answers").status_code in (401, 403)
    assert client.patch("/admin/answers/1/review").status_code in (401, 403)


# ------------------------------------------------------------------ E3: follow-ups
def test_followup_search_is_limited_to_previous_documents(monkeypatch):
    seen = {}

    def fake_search(v, k, tids=None):
        seen["tids"] = tids
        return [row(7, i, sim=0.6) for i in range(3)]

    monkeypatch.setattr(tiers.store, "search_chunks", fake_search)

    found = tiers.find_followup_context(VEC, [Citation(**CIT)])

    assert seen["tids"] == [7] and found is not None
    assert tiers.find_followup_context(VEC, []) is None  # nothing cited before: no search at all


def test_followup_below_bar_or_too_few_chunks_is_none(monkeypatch):
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k, tids=None: [row(7, i, sim=0.4) for i in range(3)])
    assert tiers.find_followup_context(VEC, [Citation(**CIT)]) is None
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k, tids=None: [row(7, 0, sim=0.9)])
    assert tiers.find_followup_context(VEC, [Citation(**CIT)]) is None


@patch("src.pipeline.can_context_answer_followup")
@patch("src.pipeline.classify_intent")
@patch("src.pipeline.rewrite_query")
@patch("src.generation.generate.complete")
def test_followup_uses_stored_chunks_without_context_check_llm(mock_complete, mock_rewrite, mock_intent, mock_check,
                                                               pg_mode, monkeypatch):
    from src.router import RouteIntent

    mock_intent.return_value = RouteIntent.FOLLOW_UP
    monkeypatch.setattr(tiers.store, "search_chunks", lambda v, k, tids=None: [row(7, i, f"t{i}", 0.6) for i in range(3)])
    mock_complete.return_value = llm_result("For 6 months the same Act applies [1].")
    store = SessionStore()
    session = store.get_or_create(None)
    session.last_context_text, session.last_citations = "[1] old\n- x", [Citation(**CIT)]
    store.save(session)

    answer = pipeline.answer_question("what if it is 6 months?", session_id=session.session_id, session_store=store)

    assert "same Act applies" in answer
    mock_check.assert_not_called()
    mock_rewrite.assert_not_called()
