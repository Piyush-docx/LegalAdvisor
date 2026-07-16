from src.generation.prompt import build_prompt
from src.retrieval.context import Citation


def make_citation(title="Hs Bedi vs NHAI on 14 May, 2015", url="https://indiankanoon.org/doc/183757259/"):
    return Citation(title=title, docsource="Delhi High Court", publishdate="2015-05-14", url=url)


def test_build_prompt_includes_question_context_and_citations():
    prompt = build_prompt(
        question="Can my landlord keep my deposit?",
        context_text="The security deposit must be refunded upon vacating the premises.",
        citations=[make_citation()],
    )

    assert "Can my landlord keep my deposit?" in prompt
    assert "The security deposit must be refunded upon vacating the premises." in prompt
    assert "Hs Bedi vs NHAI on 14 May, 2015" in prompt
    assert "https://indiankanoon.org/doc/183757259/" in prompt


def test_build_prompt_instructs_grounded_answer_only():
    prompt = build_prompt(
        question="q",
        context_text="context",
        citations=[make_citation()],
    )

    lowered = prompt.lower()
    assert "cite" in lowered
    assert "only" in lowered and "retrieved" in lowered


def test_build_prompt_instructs_no_personalized_advice():
    prompt = build_prompt(
        question="q",
        context_text="context",
        citations=[make_citation()],
    )

    lowered = " ".join(prompt.lower().split())
    assert "never give personalised legal advice" in lowered or "never give personalized legal advice" in lowered


def test_build_prompt_lists_multiple_citations():
    citations = [
        make_citation(title="Case A", url="https://indiankanoon.org/doc/1/"),
        make_citation(title="Case B", url="https://indiankanoon.org/doc/2/"),
    ]

    prompt = build_prompt(question="q", context_text="context", citations=citations)

    assert "Case A" in prompt
    assert "Case B" in prompt
    assert "https://indiankanoon.org/doc/1/" in prompt
    assert "https://indiankanoon.org/doc/2/" in prompt
