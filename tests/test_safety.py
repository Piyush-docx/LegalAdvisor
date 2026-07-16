from src.generation.safety import attach_disclaimer_and_attribution
from src.retrieval.context import Citation


def make_citation(title="Hs Bedi vs NHAI on 14 May, 2015", url="https://indiankanoon.org/doc/183757259/"):
    return Citation(title=title, docsource="Delhi High Court", publishdate="2015-05-14", url=url)


def test_attach_disclaimer_and_attribution_includes_original_answer():
    result = attach_disclaimer_and_attribution(
        "The security deposit must be refunded.", [make_citation()]
    )

    assert "The security deposit must be refunded." in result


def test_attach_disclaimer_and_attribution_includes_ikanoon_credit():
    result = attach_disclaimer_and_attribution("answer text", [make_citation()])

    assert "indian kanoon" in result.lower() or "ikanoon" in result.lower()


def test_attach_disclaimer_and_attribution_includes_not_advice_disclaimer():
    result = attach_disclaimer_and_attribution("answer text", [make_citation()])

    lowered = result.lower()
    assert "not" in lowered and ("advice" in lowered)
    assert "lawyer" in lowered


def test_attach_disclaimer_and_attribution_includes_citation_links():
    citations = [
        make_citation(title="Case A", url="https://indiankanoon.org/doc/1/"),
        make_citation(title="Case B", url="https://indiankanoon.org/doc/2/"),
    ]

    result = attach_disclaimer_and_attribution("answer text", citations)

    assert "Case A" in result
    assert "https://indiankanoon.org/doc/1/" in result
    assert "Case B" in result
    assert "https://indiankanoon.org/doc/2/" in result


def test_attach_disclaimer_and_attribution_handles_no_citations():
    result = attach_disclaimer_and_attribution("answer text", [])

    assert "answer text" in result
    assert "indian kanoon" in result.lower() or "ikanoon" in result.lower()
