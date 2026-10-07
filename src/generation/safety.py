from src.retrieval.context import Citation

DISCLAIMER = (
    "This is general legal information, not personalised legal advice. "
    "For anything specific to your situation, please consult a lawyer."
)

ATTRIBUTION = "Powered by Indian Kanoon (indiankanoon.org)."


def attach_disclaimer_and_attribution(
    answer: str, citations: list[Citation], cited: list[int] | None = None
) -> str:
    """Append the sources, the disclaimer and the IKanoon attribution.

    `cited` holds the 1-based numbers of the sources the answer actually used; only those are listed
    (keeping their numbers, so "[2]" in the text matches "[2]" in the list). With no `cited` the
    whole list is shown."""
    parts = [answer]

    if citations:
        numbers = cited or list(range(1, len(citations) + 1))
        lines = "\n".join(f"- [{n}] {citations[n - 1].title}: {citations[n - 1].url}" for n in numbers)
        parts.append(f"Sources:\n{lines}")

    parts.append(DISCLAIMER)
    parts.append(ATTRIBUTION)

    return "\n\n".join(parts)
