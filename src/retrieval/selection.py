from src.retrieval.schemas import SearchDoc, SearchResult


def select_top_docs(result: SearchResult, n: int = 5) -> list[SearchDoc]:
    """Take the top N docs in raw search-rank order (no court-tier reranking)."""
    return result.docs[:n]
