from src.retrieval.schemas import SearchDoc, SearchResult
from src.retrieval.selection import select_top_docs


def make_doc(tid: int, title: str) -> SearchDoc:
    return SearchDoc(
        tid=tid,
        title=title,
        doctype=1002,
        docsource="Delhi High Court",
        publishdate="2024-01-01",
        headline="headline",
        docsize=1000,
        numcites=0,
        numcitedby=0,
    )


def test_select_top_docs_returns_first_five_in_original_order():
    docs = [make_doc(i, f"Doc {i}") for i in range(10)]
    result = SearchResult(docs=docs, found="1 - 10 of 10")

    selected = select_top_docs(result, n=5)

    assert len(selected) == 5
    assert [d.tid for d in selected] == [0, 1, 2, 3, 4]


def test_select_top_docs_does_not_rerank_by_court_tier():
    # Regression guard for the deliberate product decision: Strategy A
    # (raw search rank), not tier-first reranking. A district court doc
    # ranked first by the API should stay first here.
    district_court_doc = make_doc(1, "District Court Case")
    district_court_doc.doctype = 10000
    district_court_doc.docsource = "Delhi District Court"

    high_court_doc = make_doc(2, "High Court Case")

    result = SearchResult(docs=[district_court_doc, high_court_doc], found="1 - 2 of 2")

    selected = select_top_docs(result, n=5)

    assert selected[0].tid == 1


def test_select_top_docs_handles_fewer_docs_than_requested():
    docs = [make_doc(i, f"Doc {i}") for i in range(3)]
    result = SearchResult(docs=docs, found="1 - 3 of 3")

    selected = select_top_docs(result, n=5)

    assert len(selected) == 3
