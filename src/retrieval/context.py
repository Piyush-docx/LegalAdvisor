import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from src.retrieval.document import extract_substantive_text, fetch_document
from src.retrieval.search import search_ikanoon
from src.retrieval.selection import select_top_docs


class Citation(BaseModel):
    title: str
    docsource: str
    publishdate: str
    url: str


def build_context(
    search_query: str, max_docs: int = 5
) -> tuple[str, list[Citation]]:
    search_result = search_ikanoon(search_query)
    top_docs = select_top_docs(search_result, n=max_docs)

    if not top_docs:
        return "", []

    # Fetch all documents in parallel to reduce end-to-end latency
    with ThreadPoolExecutor(max_workers=min(len(top_docs), 5)) as executor:
        full_docs = list(executor.map(lambda doc: fetch_document(doc.tid), top_docs))

    chunks: list[str] = []
    citations: list[Citation] = []
    for doc, full in zip(top_docs, full_docs):
        chunks.append(extract_substantive_text(full.doc))
        citations.append(
            Citation(
                title=re.sub(r"<[^>]+>", "", doc.title),
                docsource=doc.docsource,
                publishdate=doc.publishdate,
                url=f"https://indiankanoon.org/doc/{doc.tid}/",
            )
        )

    context_text = "\n\n---\n\n".join(chunks)
    return context_text, citations
