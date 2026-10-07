from unittest.mock import MagicMock, patch

import pytest

from src import guardrails as g
from src.generation.prompt import build_prompt
from src.generation.safety import attach_disclaimer_and_attribution
from src.retrieval import context as ctx
from src.retrieval.context import BudgetExceeded, Citation, build_context, relaxation_ladder
from src.retrieval.rewrite import normalize_search_query
from src.retrieval.schemas import DocumentText, SearchDoc, SearchResult
from src.retrieval.selection import doc_tier, select_top_docs


# ------------------------------------------------------------------ query normalisation / ladder
@pytest.mark.parametrize("raw,expected", [
    ('"cheque bounce" ANDD punishment ANDD laws', '"cheque bounce" ANDD punishment doctypes:laws'),
    ('"a" ANDD b doctypes: laws', '"a" ANDD b doctypes:laws'),
    ('"a" ANDD b doctypes:LAWS', '"a" ANDD b doctypes:laws'),
    ('"labour laws" ANDD wages', '"labour laws" ANDD wages'),          # a real "laws" inside a phrase is untouched
    ('"x" ANDD y doctypes:judgments', '"x" ANDD y doctypes:judgments'),
    ('`"a" ANDD b doctypes:laws`\nExplanation: blah', '"a" ANDD b doctypes:laws'),  # first line only, fences stripped
    ('', ''),
])
def test_normalize_search_query(raw, expected):
    assert normalize_search_query(raw) == expected


def test_relaxation_ladder_drops_extra_terms_then_the_filter():
    q = '"security deposit" ANDD tenancy ANDD refund doctypes:laws'
    assert relaxation_ladder(q) == ['"security deposit" doctypes:laws', '"security deposit"']


def test_relaxation_ladder_without_phrase_uses_first_terms_and_skips_duplicates():
    assert relaxation_ladder("eviction ANDD tenancy ANDD notice") == ["eviction ANDD tenancy"]
    assert relaxation_ladder('"child custody"') == []
    assert relaxation_ladder("") == []


# ------------------------------------------------------------------ document reranking
def doc(tid, title="T", doctype=1020, source="Karnataka High Court", headline="x"):
    return SearchDoc(tid=tid, title=title, doctype=doctype, docsource=source, publishdate="2020-01-01",
                     headline=headline, docsize=1, numcites=0, numcitedby=0)


def result(*docs):
    return SearchResult(docs=list(docs), found=f"1 - {len(docs)}")


def test_doc_tiers_from_ikanoon_codes():
    assert doc_tier(doc(1, doctype=91, source="State of Rajasthan - Act")) == "law"
    assert doc_tier(doc(1, doctype=1000, source="Supreme Court of India")) == "supreme"
    assert doc_tier(doc(1, doctype=1020)) == "high"
    assert doc_tier(doc(1, doctype=10000, source="Delhi District Court")) == "lower"
    assert doc_tier(doc(1, doctype=40, source="Tribunal")) == "other"


def test_equal_docs_keep_ikanoon_order():
    docs = [doc(i) for i in range(6)]
    assert [d.tid for d in select_top_docs(result(*docs), n=4)] == [0, 1, 2, 3]


def test_close_calls_are_decided_by_source_tier_but_rank_still_dominates():
    # rank 0 (district) vs rank 1 (Act): the Act's bonus wins a close call...
    close = result(doc(1, doctype=10000, source="Delhi District Court"), doc(2, doctype=91, source="State - Act"))
    assert select_top_docs(close, n=1)[0].tid == 2
    # ...but a document ranked far lower by IKanoon does not leapfrog the top hit on tier alone.
    far = result(*[doc(i) for i in range(1, 9)], doc(99, doctype=91, source="State - Act"))
    assert select_top_docs(far, n=1)[0].tid == 1


def test_keyword_match_in_title_or_headline_breaks_close_calls():
    docs = [doc(i, headline="unrelated words") for i in range(6)]
    docs[2] = doc(2, headline="the <b>security</b> <b>deposit</b> is refunded")  # ranked 3rd by IKanoon, best match
    picked = [d.tid for d in select_top_docs(result(*docs), n=2, query='"security deposit" ANDD refund')]
    assert picked == [0, 2]  # the matching neighbour beats the unrelated doc ranked just above it


def test_empty_result_selects_nothing():
    assert select_top_docs(result(), n=5) == []


# ------------------------------------------------------------------ build_context
def act_html(heading, body):
    return f'<section class="akn-section"><h3>{heading}</h3><section><span>{body}</span></section></section>'


def make_docs():
    """doc 1: security-deposit Act with 5 sections; doc 2: unrelated rent Act; doc 3: a judgment."""
    deposit_sections = "".join(
        act_html(f"{i}. Security deposit rule {i}.", f"The security deposit shall be refunded to the tenant within one month, rule {i}. " * 3)
        for i in range(1, 6)
    )
    pages = {
        1: f"<div>{deposit_sections}</div>",
        2: "<div>" + act_html("4. Rent.", "Rent shall be paid monthly by the tenant to the landlord on time. " * 3) + "</div>",
        3: '<p data-structure="Facts">The tenant asked for the security deposit back after vacating the premises and the landlord refused. </p>',
    }
    return pages


def patch_ikanoon(pages, search_results):
    """search_results: list of SearchResult returned by successive searches."""
    search = MagicMock(side_effect=list(search_results))
    fetch = MagicMock(side_effect=lambda tid: DocumentText(
        tid=tid, title="t", docsource="s", publishdate="p", doc=pages[tid], numcites=0, numcitedby=0))
    return patch.object(ctx, "search_ikanoon", search), patch.object(ctx, "fetch_document", fetch), search, fetch


def run_context(search_results, **kwargs):
    pages = make_docs()
    p_search, p_fetch, search, fetch = patch_ikanoon(pages, search_results)
    docs = result(doc(1, "Deposit Act", 91, "State - Act"), doc(2, "Rent Act", 91, "State - Act"), doc(3, "Case v Case"))
    search_results = search_results or [docs]
    with p_search, p_fetch:
        info = {}
        out = build_context('"security deposit" ANDD refund', question="my deposit is not refunded", info=info, **kwargs)
    return out, info, search, fetch


def test_context_is_numbered_cited_and_capped_per_document():
    docs = result(doc(1, "Deposit Act", 91, "State - Act"), doc(2, "Rent Act", 91, "State - Act"), doc(3, "Case v Case"))
    (text, cits), info, search, fetch = run_context([docs])

    assert [c.title for c in cits][0] == "Deposit Act"
    assert text.startswith("[1] Deposit Act (State - Act, 2020-01-01)")
    assert text.count("- ") >= 3
    assert text.split(ctx.SOURCE_SEPARATOR)[0].count("\n- ") <= 3          # per-document cap
    assert sum(b.count("\n- ") for b in text.split(ctx.SOURCE_SEPARATOR)) <= 8  # total cap
    assert len(cits) == len(text.split(ctx.SOURCE_SEPARATOR))              # [n] numbers match the citation list
    assert all(isinstance(c, Citation) for c in cits)
    assert info["searches"] == 1 and info["relaxed"] is False
    assert info["documents_fetched"] == 3 and info["documents_reused"] == 0


def test_irrelevant_document_does_not_crowd_out_relevant_ones():
    docs = result(doc(1, "Deposit Act", 91, "State - Act"), doc(2, "Rent Act", 91, "State - Act"), doc(3, "Case v Case"))
    (text, cits), *_ = run_context([docs], max_chunks=4, per_doc_cap=2)

    assert "Security deposit rule" in text
    assert "Rent shall be paid" not in text  # never matched the query terms


def test_empty_search_is_relaxed_and_flagged():
    empty = SearchResult(docs=[], found="No matching results")
    full = result(doc(1, "Deposit Act", 91, "State - Act"))
    (text, cits), info, search, fetch = run_context([empty, full])

    assert info["relaxed"] is True and info["searches"] == 2 and len(cits) == 1
    assert search.call_args_list[1].args[0] == '"security deposit"'.replace('"security deposit"', '"security deposit"')  # looser query


def test_all_searches_empty_returns_nothing_after_trying_the_ladder():
    empty = SearchResult(docs=[], found="No matching results")
    (text, cits), info, *_ = run_context([empty, empty])  # this query has no filter: one relaxation
    assert (text, cits) == ("", []) and info["searches"] == 2


def test_budget_is_charged_per_search_and_per_fetched_document():
    spent = []
    docs = result(doc(1, "Deposit Act", 91, "State - Act"), doc(3, "Case v Case"))
    run_context([docs], consume=lambda n: spent.append(n) or True)
    assert spent == [1, 2]  # one search, then two documents


def test_budget_refusal_stops_before_any_billable_call():
    p_search, p_fetch, search, fetch = patch_ikanoon(make_docs(), [result(doc(1))])
    with p_search, p_fetch, pytest.raises(BudgetExceeded):
        build_context('"x"', consume=lambda n: False)
    search.assert_not_called()
    fetch.assert_not_called()


def test_budget_refusal_before_fetching_documents():
    answers = iter([True, False])  # the search is allowed, the document fetches are not
    p_search, p_fetch, search, fetch = patch_ikanoon(make_docs(), [result(doc(1, "Deposit Act", 91, "State - Act"))])
    with p_search, p_fetch, pytest.raises(BudgetExceeded):
        build_context('"x"', consume=lambda n: next(answers))
    fetch.assert_not_called()


def test_stored_documents_are_reused_and_new_ones_are_stored(monkeypatch):
    pages = make_docs()
    docs = result(doc(1, "Deposit Act", 91, "State - Act"), doc(3, "Case v Case"))
    p_search, p_fetch, search, fetch = patch_ikanoon(pages, [docs])
    monkeypatch.setattr(ctx, "using_postgres", lambda: True)
    get_fresh = MagicMock(return_value={1: {"text": pages[1]}})
    upsert = MagicMock()
    monkeypatch.setattr(ctx.store, "get_fresh_documents", get_fresh)
    monkeypatch.setattr(ctx.store, "upsert_document", upsert)
    spent = []

    with p_search, p_fetch:
        info = {}
        text, cits = build_context('"security deposit" ANDD refund', info=info, consume=lambda n: spent.append(n) or True)

    assert [c.call_args.args[0] for c in [fetch]] == [3]          # only the missing document was downloaded
    assert info["documents_fetched"] == 1 and info["documents_reused"] == 1
    assert spent == [1, 1]                                         # billed for 1 search + 1 fetch, not 2
    assert upsert.call_args.kwargs["tid"] == 3 and upsert.call_args.kwargs["text"] == pages[3]
    assert len(cits) == 2


def test_storage_failure_never_breaks_retrieval(monkeypatch):
    pages = make_docs()
    p_search, p_fetch, *_ = patch_ikanoon(pages, [result(doc(1, "Deposit Act", 91, "State - Act"))])
    monkeypatch.setattr(ctx, "using_postgres", lambda: True)
    monkeypatch.setattr(ctx.store, "get_fresh_documents", MagicMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(ctx.store, "upsert_document", MagicMock(side_effect=RuntimeError("db down")))

    with p_search, p_fetch:
        text, cits = build_context('"security deposit"')

    assert len(cits) == 1 and "[1]" in text


# ------------------------------------------------------------------ citation markers
def test_process_citations_keeps_valid_and_removes_invalid_markers():
    text, cited, flags = g.process_citations("Deposits are refunded [1]. Also [3] and [7] apply [2] .", 3)

    assert cited == [1, 2, 3]
    assert "[7]" not in text and "[1]" in text and "[2]" in text
    assert "invalid_citation" in flags


def test_process_citations_flags_answers_that_cite_nothing():
    text, cited, flags = g.process_citations("A plain answer with no markers.", 2)
    assert cited == [] and flags == ["no_citations"]
    assert g.process_citations("Anything.", 0) == ("Anything.", [], [])


def test_process_citations_ignores_non_marker_brackets():
    text, cited, flags = g.process_citations("See clause [a] and [2024] and [1].", 2)
    assert "[2024]" in text and cited == [1] and flags == []


# ------------------------------------------------------------------ sources list and prompt
def cit(i):
    return Citation(title=f"Source {i}", docsource="HC", publishdate="2020", url=f"https://indiankanoon.org/doc/{i}/")


def test_only_cited_sources_are_listed_with_their_original_numbers():
    out = attach_disclaimer_and_attribution("Answer [2].", [cit(1), cit(2), cit(3)], cited=[2])

    assert "- [2] Source 2: https://indiankanoon.org/doc/2/" in out
    assert "Source 1" not in out and "Source 3" not in out
    assert "Powered by Indian Kanoon" in out


def test_all_sources_listed_when_nothing_was_cited():
    out = attach_disclaimer_and_attribution("Answer.", [cit(1), cit(2)])
    assert "- [1] Source 1" in out and "- [2] Source 2" in out


def test_prompt_numbers_sources_and_sets_the_grounding_policy():
    prompt = build_prompt("q?", "[1] Title\n- text", [cit(1), cit(2)])

    assert "[1] Source 1: https://indiankanoon.org/doc/1/" in prompt and "[2] Source 2:" in prompt
    flat = " ".join(prompt.split())
    assert 'begins exactly with "General background (not from the retrieved sources):"' in flat
    assert "never invent section numbers" in flat
