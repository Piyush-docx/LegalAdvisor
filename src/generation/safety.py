from src.retrieval.context import Citation

DISCLAIMER = (
    "This is general legal information, not personalised legal advice. "
    "For anything specific to your situation, please consult a lawyer."
)

ATTRIBUTION = "Powered by Indian Kanoon (indiankanoon.org)."


def attach_disclaimer_and_attribution(answer: str, citations: list[Citation]) -> str:
    parts = [answer]

    if citations:
        citation_lines = "\n".join(f"- {c.title}: {c.url}" for c in citations)
        parts.append(f"Sources:\n{citation_lines}")

    parts.append(DISCLAIMER)
    parts.append(ATTRIBUTION)

    return "\n\n".join(parts)
