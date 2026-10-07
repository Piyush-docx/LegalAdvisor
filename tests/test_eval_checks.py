from evals import checks
from src.generation.safety import ATTRIBUTION, DISCLAIMER


def _answer(body, urls=()):
    src = "\n".join(f"- Title: {u}" for u in urls)
    parts = [body]
    if urls:
        parts.append(f"Sources:\n{src}")
    parts += [DISCLAIMER, ATTRIBUTION]
    return "\n\n".join(parts)


def test_split_answer_extracts_body_urls_and_flags():
    parts = checks.split_answer(_answer("Body text.", ["https://indiankanoon.org/doc/1/"]))
    assert parts["body"] == "Body text."
    assert parts["source_urls"] == ["https://indiankanoon.org/doc/1/"]
    assert parts["has_disclaimer"] and parts["has_attribution"]


def test_ungrounded_sections_flags_numbers_missing_from_context():
    body = "Under Section 138 and s. 143A the drawer is liable; also Section 999."
    context = "138. Dishonour of cheque ... 143A. Power to direct interim compensation"
    assert checks.ungrounded_sections(body, context) == ["999"]


def test_ends_cleanly_detects_cut_off_answer():
    assert checks.ends_cleanly("A full sentence.")
    assert not checks.ends_cleanly("A list that stops at **Mediation")


def test_first_context_rank_and_source_hit():
    context = "A case about rent." + checks.DOC_SEPARATOR + "Section 138 of the Negotiable Instruments Act"
    assert checks.first_context_rank(["negotiable instruments"], context) == 2
    assert checks.first_context_rank(["Contract Act"], context) is None
    assert checks.source_hit(["negotiable instruments act"], "the Negotiable Instruments Act applies")
    assert checks.source_hit([], "anything")


def test_run_checks_truncation_and_route():
    case = {"behavior": "answer", "expected_route": "NEW_QUERY", "expected_sources_any": ["Section 138"],
            "expect_retrieval": True, "must_not": []}
    answer = _answer("Section 138 applies.", ["https://indiankanoon.org/doc/1/"])
    turn = {"intent": "NEW_QUERY", "stop_reason": "MAX_TOKENS", "ikanoon_calls": 6, "error": None}
    out = checks.run_checks(case, answer, "138. Dishonour", ["Section 138"], ["https://indiankanoon.org/doc/1/"], turn)
    assert out["not_truncated"] is False
    assert out["route_ok"] is True
    assert out["citations_valid"] is True
    assert out["sections_grounded"] is True
    assert out["no_retrieval"] is None


def test_run_checks_no_retrieval_for_chitchat_style_case():
    case = {"behavior": "chitchat", "expected_route": "CHITCHAT", "expected_sources_any": [],
            "expect_retrieval": False, "must_not": []}
    turn = {"intent": "CHITCHAT", "stop_reason": None, "ikanoon_calls": 0, "error": None}
    out = checks.run_checks(case, "Hello!", "", [], [], turn)
    assert out["no_retrieval"] is True and out["route_ok"] is True
