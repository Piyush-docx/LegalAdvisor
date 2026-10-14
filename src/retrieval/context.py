"""Build the numbered, chunk-based context the answer model sees.

Flow: search (with a relaxation ladder when IKanoon finds nothing) -> rerank documents ->
reuse stored documents, fetch only the missing ones -> chunk -> keyword-rank every chunk -> keep the
best `max_chunks` (at most `per_doc_cap` per document) -> numbered sources.

Source numbers are document numbers: "[2]" in an answer refers to the second Citation returned here.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
import logging
import re

from pydantic import BaseModel

from src import store
from src.db import using_postgres
from src.retrieval.chunking import Chunk, chunk_document
from src.retrieval.document import fetch_document
from src.retrieval.lexical import rank_chunks
from src.retrieval.search import search_ikanoon
from src.retrieval.selection import select_top_docs
from src.retrieval.states import mentions_state

logger = logging.getLogger(__name__)

SOURCE_SEPARATOR = "\n\n---\n\n"
MAX_RELAXATIONS = 2  # extra searches (Rs 0.50 each) tried when a search returns nothing

_LABELS = {
    "Facts": "Facts", "Issue": "Issue", "CDiscource": "Court's reasoning", "Conclusion": "Conclusion",
    "Precedent": "Precedent cited", "PetArg": "Petitioner's argument", "RespArg": "Respondent's argument",
}


class Citation(BaseModel):
    title: str
    docsource: str
    publishdate: str
    url: str


class BudgetExceeded(Exception):
    """The daily IKanoon call budget does not cover this retrieval."""


# --------------------------------------------------------------------------- query relaxation
_QUOTED = re.compile(r'"[^"]+"')
_FILTER = re.compile(r"doctypes:\w+", re.IGNORECASE)
_OPERATORS = {"andd", "orr", "and", "or"}


def relaxation_ladder(query: str) -> list[str]:
    """Looser versions of `query`, tried in order when a search returns nothing.

    Observed on IKanoon: '"phrase" ANDD term ANDD term doctypes:laws' often returns nothing because
    every term is required. Dropping the extra terms, then the doctype filter, finds results."""
    phrases = _QUOTED.findall(query)
    filters = _FILTER.findall(query)
    rest = _FILTER.sub(" ", _QUOTED.sub(" ", query))
    terms = [w for w in re.findall(r"[A-Za-z0-9']+", rest) if w.lower() not in _OPERATORS]
    core = phrases[0] if phrases else " ANDD ".join(terms[:2])
    if not core:
        return []
    candidates = []
    if filters:
        candidates.append(f"{core} {filters[0]}")
    candidates.append(core)
    out: list[str] = []
    for c in candidates:
        if c.strip() and c != query and c not in out:
            out.append(c)
    return out[:MAX_RELAXATIONS]


# --------------------------------------------------------------------------- Act-name queries
_ACT_WORDS = re.compile(r"\b(act|code|sanhita|adhiniyam|rules|regulations)\b", re.IGNORECASE)
_TITLE_NOISE = {"the", "of", "in", "and", "act", "section", "code"}


def _title_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", re.sub(r"<[^>]+>", " ", text).lower()) if w not in _TITLE_NOISE}


def names_an_act(query: str) -> bool:
    """True when the query asks for a law by name, e.g. '"Payment of Wages Act, 1936" doctypes:laws'."""
    phrases = _QUOTED.findall(query)
    return bool(phrases) and bool(_ACT_WORDS.search(phrases[0]))


def act_in_titles(query: str, docs) -> bool:
    """Did IKanoon return at least one document whose title contains the named Act?

    The Act name comes from the model's memory; this check stops a wrong guess from steering the answer."""
    wanted = _title_tokens(_QUOTED.findall(query)[0])
    return bool(wanted) and any(wanted <= _title_tokens(d.title) for d in docs)


# --------------------------------------------------------------------------- helpers
def _clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title)


def _stored_documents(tids: list[int]) -> dict[int, dict]:
    """Documents already in our database (PostgreSQL only). Failures just mean 'fetch from IKanoon'."""
    if not using_postgres():
        return {}
    try:
        return store.get_fresh_documents(tids)
    except Exception:  # noqa: BLE001
        logger.exception("could not read stored documents")
        return {}


def _remember(doc, html: str) -> None:
    if not using_postgres():
        return
    try:
        store.upsert_document(
            tid=doc.tid, title=_clean_title(doc.title), docsource=doc.docsource, publishdate=doc.publishdate,
            doctype=doc.doctype, url=f"https://indiankanoon.org/doc/{doc.tid}/", text=html,
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not store document %s", doc.tid)


class _Candidate:
    """A chunk plus the document it came from (rank_chunks only needs `.text`)."""

    def __init__(self, doc_index: int, chunk: Chunk):
        self.doc_index, self.chunk, self.text = doc_index, chunk, chunk.text


def _pick_chunks(candidates: list[_Candidate], search_query: str, question: str | None,
                 max_chunks: int, per_doc_cap: int) -> list[_Candidate]:
    picked: list[_Candidate] = []
    per_doc: Counter = Counter()
    for cand, _score in rank_chunks(candidates, search_query, question, top_k=len(candidates)):
        if len(picked) >= max_chunks:
            break
        if per_doc[cand.doc_index] < per_doc_cap:
            picked.append(cand)
            per_doc[cand.doc_index] += 1
    if not picked:  # nothing matched any query term: fall back to the openings of the top documents
        for cand in candidates:
            if len(picked) >= max_chunks:
                break
            if per_doc[cand.doc_index] < per_doc_cap:
                picked.append(cand)
                per_doc[cand.doc_index] += 1
    return picked


def _stored_text(chunk: Chunk) -> str:
    return f"{_LABELS.get(chunk.label, chunk.label)}: {chunk.text}" if chunk.label else chunk.text


def context_from_stored(rows: list[dict], max_chunks: int = 8, per_doc_cap: int = 3) -> tuple[str, list[Citation]]:
    """Numbered context from chunk rows returned by store.search_chunks (best match first).

    Same shape as build_context: documents are numbered in order of their best chunk."""
    per_doc: dict[int, list[dict]] = {}
    taken = 0
    for row in rows:
        if taken >= max_chunks:
            break
        if len(per_doc.setdefault(row["tid"], [])) < per_doc_cap:
            per_doc[row["tid"]].append(row)
            taken += 1
    blocks: list[str] = []
    citations: list[Citation] = []
    for mine in per_doc.values():
        if not mine:
            continue
        first = mine[0]
        citations.append(Citation(title=first["title"], docsource=first["docsource"],
                                  publishdate=first["publishdate"], url=first["url"]))
        header = f"[{len(citations)}] {first['title']} ({first['docsource']}, {first['publishdate']})"
        blocks.append(header + "\n" + "\n".join(f"- {r['text']}" for r in sorted(mine, key=lambda r: r["idx"])))
    return SOURCE_SEPARATOR.join(blocks), citations


def _render(label: str | None, text: str) -> str:
    if not label:
        return f"- {text}"
    return f"- {_LABELS.get(label, label)}: {text}"


TOPIC_EXTRA_DOCS = 3


def _topic_docs(topic_query: str, consume, info: dict) -> list:
    """Hits for the topic query, loosened step by step until something comes back."""
    for query in [topic_query] + relaxation_ladder(topic_query):
        if consume and not consume(1):
            raise BudgetExceeded("daily IKanoon budget exhausted")
        info["searches"] += 1
        found = search_ikanoon(query)
        if found.docs:
            info["topic_query_used"] = query
            return found.docs
    return []


def _interleave(first: list, second: list) -> list:
    """Alternate the two result lists (first one leading), dropping repeated documents."""
    out, seen = [], set()
    for pair in zip_longest(first, second):
        for doc in pair:
            if doc is not None and doc.tid not in seen:
                seen.add(doc.tid)
                out.append(doc)
    return out


# --------------------------------------------------------------------------- main entry point
def build_context(
    search_query: str,
    question: str | None = None,
    max_docs: int = 5,
    max_chunks: int = 8,
    per_doc_cap: int = 3,
    consume=None,
    info: dict | None = None,
) -> tuple[str, list[Citation]]:
    """Return (numbered context text, one Citation per document used).

    `consume(n)` is called before every billable IKanoon call and must return False when the daily
    budget is spent (-> BudgetExceeded). `info`, if given, is filled with what happened: searches,
    relaxed, query_used, act_requested / act_matched (was a law asked for by name, and did its title come
    back), documents_fetched, documents_reused."""
    info = info if info is not None else {}
    info.update(searches=0, relaxed=False, documents_fetched=0, documents_reused=0,
                act_requested=False, act_matched=False, query_used=None)

    # search_query may hold several lines: the Act query first, then the topic query (see rewrite_query).
    queries = [ln.strip() for ln in search_query.splitlines() if ln.strip()] or [search_query]
    attempts = queries + relaxation_ladder(queries[-1])
    act_requested = any(names_an_act(q) for q in queries)
    chosen = fallback = None
    matched = False  # True only when an Act query was accepted because its title came back
    for attempt, query in enumerate(attempts):
        if consume and not consume(1):
            raise BudgetExceeded("daily IKanoon budget exhausted")
        info["searches"] += 1
        found = search_ikanoon(query)
        if not found.docs:
            continue
        if names_an_act(query) and not act_in_titles(query, found.docs):
            fallback = fallback or (attempt, query, found)  # the guessed Act is not what came back
            continue
        chosen = (attempt, query, found)
        matched = names_an_act(query)
        break
    chosen = chosen or fallback
    info.update(act_requested=act_requested, act_matched=matched)
    if chosen is None:
        return "", []
    attempt, used_query, result = chosen
    info.update(relaxed=attempt > 0, query_used=used_query)

    # An accepted Act query used to end the search, so every question about one area got the same
    # sections of that Act. The topic query says what this question is about: merge its hits in.
    topic_query = next((q for q in queries if q != used_query and not names_an_act(q)), None)
    if matched and topic_query:
        extra = _topic_docs(topic_query, consume, info)
        if extra:
            # The topic hits are specific to this question, so they lead; a few more documents are
            # considered, and chunk ranking below still decides what the model is shown.
            result = result.model_copy(update={"docs": _interleave(extra, result.docs)})
            max_docs += TOPIC_EXTRA_DOCS

    top_docs = select_top_docs(result, n=max_docs, query=search_query, prefer_central=not mentions_state(question))
    stored = _stored_documents([d.tid for d in top_docs])
    missing = [d for d in top_docs if d.tid not in stored]
    if missing and consume and not consume(len(missing)):
        raise BudgetExceeded("daily IKanoon budget exhausted")

    fetched: dict[int, str] = {}
    if missing:
        with ThreadPoolExecutor(max_workers=min(len(missing), 5)) as executor:
            for doc, full in zip(missing, executor.map(lambda d: fetch_document(d.tid), missing)):
                fetched[doc.tid] = full.doc
                _remember(doc, full.doc)
    info.update(documents_fetched=len(fetched), documents_reused=len(top_docs) - len(fetched))

    candidates: list[_Candidate] = []
    for i, doc in enumerate(top_docs):
        html = fetched.get(doc.tid) or stored[doc.tid]["text"]
        candidates.extend(_Candidate(i, c) for c in chunk_document(html))

    picked = _pick_chunks(candidates, search_query, question, max_chunks, per_doc_cap)
    if not picked:
        return "", []

    blocks: list[str] = []
    citations: list[Citation] = []
    info["chunks"] = []
    for i, doc in enumerate(top_docs):
        mine = sorted((c for c in picked if c.doc_index == i), key=lambda c: c.chunk.idx)
        if not mine:
            continue
        # What a later question can reuse: the chunk as shown to the model (heading label included).
        info["chunks"] += [{"tid": doc.tid, "idx": c.chunk.idx, "text": _stored_text(c.chunk)} for c in mine]
        citations.append(
            Citation(
                title=_clean_title(doc.title),
                docsource=doc.docsource,
                publishdate=doc.publishdate,
                url=f"https://indiankanoon.org/doc/{doc.tid}/",
            )
        )
        header = f"[{len(citations)}] {citations[-1].title} ({doc.docsource}, {doc.publishdate})"
        blocks.append(header + "\n" + "\n".join(_render(c.chunk.label, c.chunk.text) for c in mine))
    return SOURCE_SEPARATOR.join(blocks), citations
