import json
from pathlib import Path

import pytest
import responses

from src.retrieval.document import (
    clean_document_html,
    extract_substantive_text,
    fetch_document,
)
from src.retrieval.schemas import DocumentText

FIXTURES = Path(__file__).parent / "fixtures"


@responses.activate
def test_fetch_document_returns_validated_document_text():
    fixture = json.loads((FIXTURES / "document_response.json").read_text())
    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/doc/183757259/",
        json=fixture,
        status=200,
    )

    doc = fetch_document(183757259)

    assert isinstance(doc, DocumentText)
    assert doc.tid == 183757259
    assert doc.docsource == "Delhi High Court"


def test_clean_document_html_strips_page_number_spans():
    raw_html = (
        '<p data-structure="Facts" id="p_1">The tenant paid a deposit.'
        '<span class="hidden_text" id="span_1">Page 1 of 70</span></p>'
    )

    cleaned = clean_document_html(raw_html)

    assert "Page 1 of 70" not in cleaned
    assert "The tenant paid a deposit." in cleaned


def test_clean_document_html_strips_html_tags():
    raw_html = '<h2 class="doc_title">Case Title</h2><pre id="pre_1">JUDGMENT TEXT</pre>'

    cleaned = clean_document_html(raw_html)

    assert "<h2" not in cleaned
    assert "<pre" not in cleaned
    assert "Case Title" in cleaned
    assert "JUDGMENT TEXT" in cleaned


def test_clean_document_html_on_real_fixture_removes_all_tags_and_noise():
    fixture = json.loads((FIXTURES / "document_response.json").read_text())
    raw_html = fixture["doc"]

    cleaned = clean_document_html(raw_html)

    assert "<" not in cleaned
    assert ">" not in cleaned
    # Substantive content should survive
    assert "security deposit" in cleaned.lower()
    # The cleaned text should be meaningfully shorter than the raw HTML
    assert len(cleaned) < len(raw_html)


def test_extract_substantive_text_keeps_issue_facts_conclusion():
    raw_html = (
        '<p data-structure="Issue" id="p_1">What was the dispute.</p>'
        '<p data-structure="Facts" id="p_2">What happened between the parties.</p>'
        '<p data-structure="CDiscource" id="p_3">Pages of judicial reasoning and case law analysis.</p>'
        '<p data-structure="Precedent" id="p_4">Citations to twenty other judgments.</p>'
        '<p data-structure="Conclusion" id="p_5">The court held X.</p>'
    )

    result = extract_substantive_text(raw_html)

    assert "What was the dispute." in result
    assert "What happened between the parties." in result
    assert "The court held X." in result
    assert "judicial reasoning" not in result
    assert "Citations to twenty other judgments." not in result


def test_extract_substantive_text_drops_page_number_noise():
    raw_html = (
        '<p data-structure="Facts" id="p_1">The tenant paid a deposit.'
        '<span class="hidden_text" id="span_1">Page 1 of 70</span></p>'
    )

    result = extract_substantive_text(raw_html)

    assert "Page 1 of 70" not in result
    assert "The tenant paid a deposit." in result


def test_extract_substantive_text_on_real_fixture_shrinks_dramatically():
    fixture = json.loads((FIXTURES / "document_response.json").read_text())
    raw_html = fixture["doc"]

    result = extract_substantive_text(raw_html)

    # Measured reduction on this fixture is ~93% (152508 -> ~10800 chars);
    # assert a generous bound so the test isn't brittle to minor wording changes.
    assert len(result) < len(raw_html) * 0.25
    assert len(result) > 0
    assert "security deposit" in result.lower()


def test_extract_substantive_text_falls_back_when_no_structure_tags():
    # Not every IKanoon doc is guaranteed to carry data-structure tags
    # (e.g. bare statutes/acts) -- fall back to full cleaned text rather
    # than silently returning nothing.
    raw_html = "<pre>Section 5. The tenant is entitled to a refund.</pre>"

    result = extract_substantive_text(raw_html)

    assert "The tenant is entitled to a refund." in result
