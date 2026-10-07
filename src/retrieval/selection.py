import re

from src.retrieval.lexical import BM25, query_terms
from src.retrieval.schemas import SearchDoc, SearchResult

# IKanoon doctype codes (observed): Acts use many small numbers and carry "- Act" in the source name,
# 1000 is the Supreme Court, 1001-1099 are High Courts, 10000+ are district/lower courts.
_SUPREME_COURT = 1000
_HIGH_COURT = range(1001, 1100)
_LOWER_COURT_FROM = 10000

TIER_BONUS = {"law": 1.0, "supreme": 0.6, "high": 0.3, "other": 0.0, "lower": -0.2}
CENTRAL_BONUS = 0.5  # Union of India sources, when the question names no state
RANK_WEIGHT = 2.0  # how much IKanoon's own ordering counts
KEYWORD_WEIGHT = 0.5


def doc_tier(doc: SearchDoc) -> str:
    # "State of Rajasthan - Act" is a whole Act; "Union of India - Section" is one section of an Act.
    if re.search(r"\b(Act|Section)\b", doc.docsource):
        return "law"
    if doc.doctype == _SUPREME_COURT:
        return "supreme"
    if doc.doctype in _HIGH_COURT:
        return "high"
    if doc.doctype >= _LOWER_COURT_FROM:
        return "lower"
    return "other"


def select_top_docs(
    result: SearchResult, n: int = 5, query: str | None = None, prefer_central: bool = False
) -> list[SearchDoc]:
    """Pick the best `n` of the search hits.

    Score = IKanoon's own rank (kept dominant) + a bonus for the kind of source (Acts, then Supreme
    Court, then High Courts) + how well the title and snippet match the query terms. With
    `prefer_central`, Union of India sources get a further bonus (used when the question names no
    state). Ties keep IKanoon's order."""
    docs = result.docs
    if not docs:
        return []
    scores = [0.0] * len(docs)
    if query:
        terms, phrases = query_terms(query)
        plain = lambda d: re.sub(r"<[^>]+>", " ", f"{d.title} {d.headline}")  # noqa: E731
        raw = BM25([plain(d) for d in docs]).scores(terms, phrases)
        top = max(raw) or 1.0
        scores = [r / top for r in raw]
    ranked = []
    for i, doc in enumerate(docs):
        rank_score = RANK_WEIGHT * (1 - i / len(docs))
        central = CENTRAL_BONUS if prefer_central and doc.docsource.startswith("Union of India") else 0.0
        ranked.append((rank_score + TIER_BONUS[doc_tier(doc)] + central + KEYWORD_WEIGHT * scores[i], -i, doc))
    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [doc for _, _, doc in ranked[:n]]
