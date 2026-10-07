from unittest.mock import MagicMock, patch

import pytest

from evals import checks as eval_checks
from evals import run as eval_run
from evals.judge import JudgeDailyLimit
from src import guardrails as g
from src.llm import LLMUnavailable
from src.pipeline import answer_question
from src.retrieval import context as ctx
from src.retrieval.context import act_in_titles, build_context, names_an_act
from src.retrieval.rewrite import normalize_search_queries, rewrite_query
from src.retrieval.schemas import DocumentText, SearchDoc, SearchResult
from src.retrieval.selection import doc_tier, select_top_docs
from src.retrieval.states import mentions_state
from src.router import RouteIntent
from tests.helpers import llm_result

ACT_Q = '"Payment of Wages Act, 1936" doctypes:laws'
TOPIC_Q = '"unpaid wages" doctypes:laws'


def sdoc(tid, title, source="Union of India - Section", doctype=91):
    return SearchDoc(tid=tid, title=title, doctype=doctype, docsource=source, publishdate="1936-01-01",
                     headline="x", docsize=1, numcites=0, numcitedby=0)


def sresult(*docs):
    return SearchResult(docs=list(docs), found=str(len(docs)))


# ------------------------------------------------------------------ rewrite: Act line + topic line
def test_normalize_search_queries_parses_two_lines_and_repairs_each():
    text = '"Payment of Wages Act, 1936" doctypes: laws\n"unpaid wages" ANDD salary ANDD laws'
    assert normalize_search_queries(text) == [ACT_Q, '"unpaid wages" ANDD salary doctypes:laws']


def test_normalize_search_queries_drops_none_labels_and_duplicates():
    assert normalize_search_queries('NONE\n"unpaid wages" doctypes:laws') == [TOPIC_Q]
    assert normalize_search_queries(f'Line 1: {ACT_Q}\nTopic: {TOPIC_Q}\n{TOPIC_Q}') == [ACT_Q, TOPIC_Q]
    assert normalize_search_queries("Sure! Here you go") == []  # chatter is not a query
    assert normalize_search_queries("") == []


@patch("src.retrieval.rewrite.complete")
def test_rewrite_query_returns_lines_act_first(mock_complete):
    mock_complete.return_value = llm_result(f"{ACT_Q}\n{TOPIC_Q}")
    assert rewrite_query("my employer has not paid me") == f"{ACT_Q}\n{TOPIC_Q}"


@patch("src.retrieval.rewrite.complete")
def test_rewrite_query_falls_back_to_the_question_when_reply_is_unusable(mock_complete):
    mock_complete.return_value = llm_result("NONE")
    assert rewrite_query("my employer has not paid me") == "my employer has not paid me"


@patch("src.retrieval.rewrite.complete")
def test_rewrite_prompt_asks_for_the_act_by_full_name_with_year(mock_complete):
    mock_complete.return_value = llm_result(ACT_Q)
    rewrite_query("q")
    prompt = mock_complete.call_args.args[1]
    assert "Line 1 - the Act" in prompt and "with year" in prompt and "NONE" in prompt
    assert "Consumer Protection Act, 2019" in prompt  # steers away from the repealed 1986 Act


# ------------------------------------------------------------------ Act query accepted only if its title comes back
def test_names_an_act_and_title_check():
    assert names_an_act(ACT_Q) and not names_an_act(TOPIC_Q) and not names_an_act("eviction ANDD tenancy")
    right = [sdoc(1, "Section 15 in The Payment Of Wages Act, 1936")]
    wrong = [sdoc(2, "Karnataka Municipal Corporations Act, 1976", "State of Karnataka - Act")]
    assert act_in_titles(ACT_Q, right) is True
    assert act_in_titles(ACT_Q, wrong) is False
    assert act_in_titles('"Consumer Protection Act, 2019" doctypes:laws', [sdoc(3, "Section 2 in Consumer Protection Act, 2019")])


def run_context(search_results, search_query, question="my salary is unpaid", **kwargs):
    html = {i: f'<section class="akn-section"><h3>{i}. Wages rule.</h3><section><span>{"Wages shall be paid on time to the employee every month. " * 3}</span></section></section>' for i in range(1, 30)}
    search = MagicMock(side_effect=list(search_results))
    fetch = MagicMock(side_effect=lambda tid: DocumentText(tid=tid, title="t", docsource="s", publishdate="p", doc=html[tid % 29 + 1], numcites=0, numcitedby=0))
    info = {}
    with patch.object(ctx, "search_ikanoon", search), patch.object(ctx, "fetch_document", fetch):
        out = build_context(search_query, question=question, info=info, **kwargs)
    return out, info, search


def test_act_query_is_used_when_its_title_matches():
    act_docs = sresult(sdoc(1, "Section 15 in The Payment Of Wages Act, 1936"), sdoc(2, "Section 2 in The Payment Of Wages Act, 1936"))
    (text, cits), info, search = run_context([act_docs], f"{ACT_Q}\n{TOPIC_Q}")

    assert search.call_count == 1 and search.call_args.args[0] == ACT_Q
    assert info["act_requested"] and info["act_matched"] and info["relaxed"] is False
    assert info["query_used"] == ACT_Q and len(cits) == 2


def test_wrong_act_guess_falls_through_to_the_topic_query_and_is_marked_unmatched():
    wrong = sresult(sdoc(9, "Karnataka Municipal Corporations Act, 1976", "State of Karnataka - Act"))
    topic = sresult(sdoc(3, "Section 7 in Some Wages Provision"))
    (text, cits), info, search = run_context([wrong, topic], f"{ACT_Q}\n{TOPIC_Q}")

    assert [c.args[0] for c in search.call_args_list] == [ACT_Q, TOPIC_Q]
    assert info["act_requested"] is True and info["act_matched"] is False
    assert info["query_used"] == TOPIC_Q and info["relaxed"] is True


def test_when_nothing_better_exists_the_unmatched_act_result_is_still_used():
    wrong = sresult(sdoc(9, "Karnataka Municipal Corporations Act, 1976", "State of Karnataka - Act"))
    (text, cits), info, search = run_context([wrong, SearchResult(docs=[], found="No matching results"), SearchResult(docs=[], found="none")], f"{ACT_Q}\n{TOPIC_Q}")

    assert len(cits) == 1 and info["act_matched"] is False  # weak sources, but not "no sources"


def test_no_act_requested_keeps_the_old_behaviour():
    (text, cits), info, search = run_context([sresult(sdoc(1, "Section 7 in Some Provision"))], TOPIC_Q)
    assert info["act_requested"] is False and info["act_matched"] is False and len(cits) == 1


# ------------------------------------------------------------------ source preference
def test_section_documents_count_as_law_and_central_sources_get_a_bonus_when_no_state_is_named():
    section = sdoc(1, "Section 15 in The Payment Of Wages Act, 1936", "Union of India - Section")
    assert doc_tier(section) == "law"
    # IKanoon's own order stays dominant: the bonus only decides close calls between neighbouring ranks.
    filler = [sdoc(10 + i, f"Filler {i}", "State of Goa - Act") for i in range(3)]
    state = sdoc(2, "Karnataka Act", "State of Karnataka - Act")
    central = sdoc(3, "Central Act", "Union of India - Act")
    pair = sresult(*filler, state, central, *[sdoc(20 + i, f"Tail {i}", "State of Goa - Act") for i in range(5)])
    assert 3 not in [d.tid for d in select_top_docs(pair, n=3)]                       # ranked 5th: not in the top 3
    assert 3 in [d.tid for d in select_top_docs(pair, n=3, prefer_central=True)]     # the bonus lifts it a couple of places
    far = sresult(*filler, *[sdoc(30 + i, f"Mid {i}", "State of Goa - Act") for i in range(6)], central)
    assert 3 not in [d.tid for d in select_top_docs(far, n=3, prefer_central=True)]  # a distant hit is not promoted


def test_state_detection():
    assert mentions_state("my landlord in Tamil Nadu will not return the deposit")
    assert mentions_state("rent rules in delhi") and mentions_state("I live in Mumbai")
    assert not mentions_state("can my employer stop my salary") and not mentions_state(None)
    assert not mentions_state("a hairstyle named bihardi")  # whole words only


def test_central_preference_is_switched_off_when_the_question_names_a_state():
    docs = sresult(sdoc(1, "State Act", "State of Karnataka - Act"), sdoc(2, "Central Act", "Union of India - Act"))
    with patch.object(ctx, "select_top_docs", wraps=ctx.select_top_docs) as spy:
        run_context([docs], TOPIC_Q, question="my landlord in Karnataka refuses")
        run_context([docs], TOPIC_Q, question="my landlord refuses")
    assert spy.call_args_list[0].kwargs["prefer_central"] is False
    assert spy.call_args_list[1].kwargs["prefer_central"] is True


# ------------------------------------------------------------------ guardrails
def test_compound_citation_markers_are_repaired_to_plain_numbers():
    text, cited, flags = g.process_citations(
        "Notice is required [3, The Tamil Nadu Buildings Act, 1960, Section 10(2)]. Also [1, 2] and [2; 3].", 3
    )
    assert "[3]" in text and "Tamil Nadu" not in text and "Section 10(2)" not in text
    assert "[1][2]" in text and cited == [1, 2, 3] and flags == []


def test_figures_not_in_the_sources_are_flagged():
    context = "[1] Act (X, 2020)\n- Within one month after vacation of the premises the deposit shall be refunded. Three times the monthly rent."
    answer = "File before the District Commission if the value is up to ₹1 crore, within 30 days, pay a 5% fee."
    assert g.unverified_figures(answer, context) == ["₹1 crore", "5%", "30 days"]


def test_figures_present_in_the_sources_are_accepted_in_digit_or_word_form():
    context = "The deposit shall be refunded within one month. Notice of 15 days. Interest at 12 per cent. Rs. 50,000 fine."
    answer = "Refund in 1 month, 15 days notice, 12% interest and a fine of Rs 50,000."
    assert g.unverified_figures(answer, context) == []


def test_unverified_figures_get_a_note_and_flag():
    text, flags = g.apply_output_guardrails("The limit is ₹10 crore.", "Some source text about limits.", "q")
    assert "unverified_figures" in flags and "₹10 crore" in text and "could not be found" in text


def test_labour_code_and_weak_source_notes():
    text, flags = g.apply_output_guardrails("Under the Payment of Wages Act, wages are due.", "ctx", "q", weak_sources=True)
    assert {"labour_code", "weak_sources"} <= set(flags)
    assert "Code on Wages" in text and "may not be the main law" in text
    _, plain = g.apply_output_guardrails("Plain answer.", "ctx", "q")
    assert "weak_sources" not in plain and "labour_code" not in plain


# ------------------------------------------------------------------ pipeline: weak sources are flagged and never cached
@patch("src.pipeline.explain_with_llm")
@patch("src.pipeline.build_context")
@patch("src.pipeline.rewrite_query", return_value=f"{ACT_Q}\n{TOPIC_Q}")
@patch("src.pipeline.classify_intent", return_value=RouteIntent.NEW_QUERY)
def test_weak_sources_get_a_warning_and_are_not_cached(mock_c, mock_r, mock_build, mock_explain):
    from src.db import get_cached_query
    from src.generation.schemas import LLMAnswer, Usage
    from src.retrieval.context import Citation

    def fake_build(query, question=None, consume=None, info=None, **kw):
        info.update(act_requested=True, act_matched=False, relaxed=True)
        return "[1] T\n- text", [Citation(title="T", docsource="S", publishdate="p", url="https://indiankanoon.org/doc/1/")]

    mock_build.side_effect = fake_build
    mock_explain.return_value = LLMAnswer(text="An answer [1].", stop_reason="STOP", usage=Usage(input_tokens=1, output_tokens=1))

    answer = str(answer_question("my salary is unpaid"))

    assert "may not be the main law" in answer
    assert get_cached_query(f"{ACT_Q}\n{TOPIC_Q}") is None


# ------------------------------------------------------------------ evals: stricter checks
def test_general_background_paragraph_does_not_count_as_evidence():
    answer = "The sources do not cover wages.\n\nGeneral background (not from the retrieved sources): The Payment of Wages Act, 1936 applies.\n\nSources:\n- [1] X"
    assert "Payment of Wages" not in eval_checks.strip_background(answer)
    assert "Sources:" in eval_checks.strip_background(answer)


def test_retrieval_check_looks_at_titles_and_section_headings_not_body_text():
    context = ("[1] West Bengal Municipal Rules, 2010 (State, 2010)\n- Rule 5: salary may be paid under the Payment of Wages Act, 1936."
               + eval_checks.DOC_SEPARATOR +
               "[2] Section 15 in The Payment Of Wages Act, 1936 (Union of India - Section, 1936)\n- 15. Claims: text")
    hay = eval_checks.retrieval_haystack(context)
    assert "Section 15 in The Payment Of Wages Act" in hay and "Rule 5" in hay and "salary may be paid" not in hay
    assert eval_checks.first_context_rank(["Payment of Wages"], context) == 2  # not rank 1 via the passing mention


def test_daily_limit_phrases_stop_the_eval_run():
    assert eval_run._is_daily_quota(LLMUnavailable("groq: ... on tokens per day (TPD): Limit 200000"))
    assert eval_run._is_daily_quota(LLMUnavailable("groq: cooling down (daily limit)"))
    assert eval_run._is_daily_quota(RuntimeError("GenerateRequestsPerDayPerProjectPerModel"))
    assert not eval_run._is_daily_quota(RuntimeError("429 rate limit per minute"))
