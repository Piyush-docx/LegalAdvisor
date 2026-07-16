import re

from pydantic import BaseModel

from src.retrieval.document import extract_substantive_text, fetch_document
from src.retrieval.rewrite import rewrite_query
from src.retrieval.search import search_ikanoon
from src.retrieval.selection import select_top_docs


class Citation(BaseModel):
    title: str
    docsource: str
    publishdate: str
    url: str


def build_context(question: str, max_docs: int = 5) -> tuple[str, list[Citation]]:
    search_result = search_ikanoon(rewrite_query(question))
    top_docs = select_top_docs(search_result, n=max_docs)

    chunks: list[str] = []
    citations: list[Citation] = []
    for doc in top_docs:
        full = fetch_document(doc.tid)
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
