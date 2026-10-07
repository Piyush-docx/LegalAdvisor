import json
from pathlib import Path
from unittest.mock import patch

import responses

from src.retrieval.context import Citation, build_context

FIXTURES = Path(__file__).parent / "fixtures"


@responses.activate
def test_build_context_returns_cleaned_text_and_citations():
    search_fixture = json.loads((FIXTURES / "search_response.json").read_text())
    doc_fixture = json.loads((FIXTURES / "document_response.json").read_text())

    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=search_fixture,
        status=200,
    )
    # Every fetched tid in the top N hits this same registered response
    # (fixture only has real doc text for one tid; that's fine for
    # verifying orchestration shape, not per-doc content).
    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/doc/183757259/",
        json=doc_fixture,
        status=200,
    )
    for doc in search_fixture["docs"][1:5]:
        responses.add(
            responses.POST,
            f"https://api.indiankanoon.org/doc/{doc['tid']}/",
            json={**doc_fixture, "tid": doc["tid"], "title": doc["title"], "docsource": doc["docsource"]},
            status=200,
        )

    context_text, citations = build_context("security deposit refund tenant landlord")

    assert isinstance(context_text, str)
    assert len(context_text) > 0
    assert "<" not in context_text  # HTML stripped

    assert len(citations) == 5
    assert all(isinstance(c, Citation) for c in citations)
    assert citations[0].title.startswith("Hs Bedi")
    assert citations[0].url == "https://indiankanoon.org/doc/183757259/"


@responses.activate
def test_build_context_joins_multiple_docs_with_separator():
    search_fixture = json.loads((FIXTURES / "search_response.json").read_text())
    doc_fixture = json.loads((FIXTURES / "document_response.json").read_text())

    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=search_fixture,
        status=200,
    )
    for doc in search_fixture["docs"][:5]:
        responses.add(
            responses.POST,
            f"https://api.indiankanoon.org/doc/{doc['tid']}/",
            json={**doc_fixture, "tid": doc["tid"]},
            status=200,
        )

    context_text, _ = build_context("security deposit refund tenant landlord")

    assert "---" in context_text


@responses.activate
def test_build_context_stays_within_token_budget_for_five_docs():
    # Guards the cost-control decision: extract_substantive_text (not the
    # full cleaned doc) must be what feeds the LLM, so 5 docs stays cheap.
    # ~4 chars/token; budget generously at 15K tokens (~60K chars) for 5 docs
    # combined, well under the ~400K chars we measured before trimming.
    search_fixture = json.loads((FIXTURES / "search_response.json").read_text())
    doc_fixture = json.loads((FIXTURES / "document_response.json").read_text())

    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=search_fixture,
        status=200,
    )
    for doc in search_fixture["docs"][:5]:
        responses.add(
            responses.POST,
            f"https://api.indiankanoon.org/doc/{doc['tid']}/",
            json={**doc_fixture, "tid": doc["tid"]},
            status=200,
        )

    context_text, _ = build_context("security deposit refund tenant landlord")

    assert len(context_text) < 60_000
