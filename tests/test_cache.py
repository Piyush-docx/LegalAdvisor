import json
from unittest.mock import patch

from src.db import cache_query, get_cached_query, get_db
from src.pipeline import answer_question
from src.retrieval.context import Citation


def test_cache_query_roundtrip():
    # Clear cache table
    conn = get_db()
    conn.execute("DELETE FROM query_cache")
    conn.commit()

    search_query = '"test query" ANDD cache doctypes: laws'
    context_text = "Mock legal context"
    citations_data = [
        Citation(title="Case 1", docsource="Court", publishdate="2023", url="http://url").model_dump()
    ]
    citations_json = json.dumps(citations_data)
    llm_answer = "This is a cached answer."

    # Cache miss initially
    assert get_cached_query(search_query) is None

    # Insert to cache
    cache_query(search_query, context_text, citations_json, llm_answer)

    # Cache hit
    cached = get_cached_query(search_query)
    assert cached is not None
    assert cached["context_text"] == context_text
    assert cached["citations"] == citations_json
    assert cached["llm_answer"] == llm_answer


@patch("src.pipeline.build_context")
@patch("src.pipeline.explain_with_llm")
@patch("src.pipeline.rewrite_query")
@patch("src.pipeline.classify_intent")
def test_pipeline_cache_hit_bypasses_llm(
    mock_classify, mock_rewrite, mock_explain, mock_build
):
    from src.router import RouteIntent

    # Setup mocks
    mock_classify.return_value = RouteIntent.NEW_QUERY
    search_query = '"rent agreement" ANDD tenancy doctypes: laws'
    mock_rewrite.return_value = search_query

    # Pre-populate cache
    conn = get_db()
    conn.execute("DELETE FROM query_cache")
    conn.commit()
    citations_json = json.dumps(
        [Citation(title="Rent Act", docsource="SC", publishdate="2020", url="url").model_dump()]
    )
    cache_query(search_query, "Cached Context", citations_json, "Cached LLM Response")

    # Run pipeline
    response = answer_question("tell me about rent agreements")

    # Verify response comes from cache
    assert "Cached LLM Response" in response

    # Verify expensive functions were NOT called
    mock_build.assert_not_called()
    mock_explain.assert_not_called()
