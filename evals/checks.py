"""Deterministic (no-LLM) checks over one eval case's final answer."""

import re

from src.generation.safety import ATTRIBUTION, DISCLAIMER

DOC_SEPARATOR = "\n\n---\n\n"  # build_context joins one block per retrieved document, in rank order
SECTION_RE = re.compile(r"(?i)\b(?:sections?|sec\.?|ss?\.)\s*(\d+[A-Z]{0,2})")
URL_RE = re.compile(r"https?://[^\s)]+")


def split_answer(answer: str) -> dict:
    """Split a pipeline answer into body / sources / flags."""
    body = answer
    sources: list[str] = []
    if "\n\nSources:\n" in answer:
        body, rest = answer.split("\n\nSources:\n", 1)
        sources = URL_RE.findall(rest.split(DISCLAIMER)[0])
    else:
        body = answer.split(DISCLAIMER)[0]
    return {
        "body": body.strip(),
        "source_urls": sources,
        "has_disclaimer": DISCLAIMER in answer,
        "has_attribution": ATTRIBUTION in answer,
    }


_BACKGROUND = re.compile(
    r"General background \(not from the retrieved sources\):.*?(?:\n\s*\n|$)", re.DOTALL | re.IGNORECASE
)


def strip_background(text: str) -> str:
    """Remove the labelled general-knowledge paragraph: it is not evidence that the sources covered a point."""
    return _BACKGROUND.sub("", text)


def retrieval_haystack(context: str) -> str:
    """What the retrieved sources are *about*: each source header plus the section/label of each excerpt.

    Matching an expected Act anywhere inside a chunk's text is too lenient: state rules mention central
    Acts in passing without being that Act."""
    lines: list[str] = []
    for block in context.split(DOC_SEPARATOR):
        parts = block.split("\n")
        lines.append(parts[0])
        for line in parts[1:]:
            m = re.match(r"- ([^:]{1,120}):", line)
            if m:
                lines.append(m.group(1))
    return "\n".join(lines)


def ends_cleanly(body: str) -> bool:
    """Heuristic only: answers cut off by the token cap usually stop mid-sentence."""
    return bool(re.search(r"[.!?)\]\"'*:।]\s*$", body.rstrip()))


def cited_sections(body: str) -> list[str]:
    return sorted(set(SECTION_RE.findall(body)))


def ungrounded_sections(body: str, context: str) -> list[str]:
    """Section numbers named in the answer that appear nowhere in the retrieved context.

    Upper bound on groundedness: a number that is absent from the context is certainly
    unsupported; a number that is present may still be matched by coincidence."""
    missing = []
    for num in cited_sections(body):
        if not re.search(rf"\b{re.escape(num)}\b", context):
            missing.append(num)
    return missing


def source_hit(expected_any: list[str], *haystacks: str) -> bool:
    if not expected_any:
        return True
    text = "\n".join(haystacks).lower()
    return any(e.lower() in text for e in expected_any)


def first_context_rank(expected_any: list[str], context: str) -> int | None:
    """1-based rank of the first retrieved document whose text mentions an expected source."""
    for i, block in enumerate(context.split(DOC_SEPARATOR), 1):
        header = block.split("\n", 1)[0].lower()  # the source's own title, not its body text
        if any(e.lower() in header for e in expected_any):
            return i
    return None


def must_not_hits(patterns: list[str], body: str) -> list[str]:
    return [p for p in patterns if re.search(p, body, re.MULTILINE)]


def run_checks(case: dict, answer: str, context: str, citation_titles: list[str],
               citation_urls: list[str], turn: dict) -> dict:
    """Return {check_name: bool | None}. None = not applicable."""
    parts = split_answer(answer)
    body = parts["body"]
    behavior = case["behavior"]
    expected = case.get("expected_sources_any", [])
    results: dict[str, bool | None] = {}

    results["no_error"] = turn.get("error") is None

    stop = turn.get("stop_reason")
    results["not_truncated"] = None if stop is None else stop != "MAX_TOKENS"
    results["ends_cleanly"] = ends_cleanly(body) if behavior == "answer" else None

    results["disclaimer_present"] = (
        parts["has_disclaimer"] and parts["has_attribution"] if behavior == "answer" else None
    )

    if behavior == "answer" and parts["source_urls"]:
        results["citations_valid"] = all(u in set(citation_urls) for u in parts["source_urls"])
    else:
        results["citations_valid"] = None

    if behavior == "answer":
        results["sections_grounded"] = len(ungrounded_sections(body, context)) == 0
    else:
        results["sections_grounded"] = None

    if behavior in ("answer", "harm_support") and expected:
        results["expected_source_in_answer"] = source_hit(expected, strip_background(answer))
    else:
        results["expected_source_in_answer"] = None

    if behavior == "answer" and expected:
        results["expected_source_retrieved"] = source_hit(expected, retrieval_haystack(context), "\n".join(citation_titles))
    else:
        results["expected_source_retrieved"] = None

    results["must_not_ok"] = (len(must_not_hits(case.get("must_not", []), body)) == 0) if case.get("must_not") else None

    if behavior in ("answer", "chitchat") and turn.get("intent"):
        results["route_ok"] = turn["intent"] == case["expected_route"]
    else:
        results["route_ok"] = None

    if not case.get("expect_retrieval", True):
        results["no_retrieval"] = turn.get("ikanoon_calls", 0) == 0
    else:
        results["no_retrieval"] = None

    return results
