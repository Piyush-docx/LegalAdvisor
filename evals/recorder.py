"""Record/replay for the paid and non-deterministic parts of retrieval.

IKanoon search + document calls cost money, and the LLM query rewrite is non-deterministic, so
both are recorded once (``--live``) and replayed afterwards. Recordings are gzip JSON files under
``evals/recordings/`` (git-ignored: they contain IKanoon content).
"""

import gzip
import hashlib
import json
from pathlib import Path

from src.retrieval.schemas import DocumentText, SearchResult

RECORDINGS = Path(__file__).parent / "recordings"


class RecordingMissing(Exception):
    """Replay-only mode hit a call that was never recorded."""


def _key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:20]


class Recorder:
    def __init__(self, live: bool = False, fresh_rewrite: bool = False, root: Path = RECORDINGS):
        self.live = live
        self.fresh_rewrite = fresh_rewrite
        self.root = root
        # Logical IKanoon calls the pipeline made (counted whether replayed or live).
        self.calls = {"search": 0, "doc": 0}
        # Calls that actually hit the network (these are the ones that cost money).
        self.live_calls = {"search": 0, "doc": 0}

    def snapshot(self) -> dict:
        return dict(self.calls)

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{key}.json.gz"

    def _load(self, kind: str, key: str) -> dict | None:
        path = self._path(kind, key)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, kind: str, key: str, payload: dict) -> None:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def wrap_search(self, real_fn):
        def search(query: str, pagenum: int = 0) -> SearchResult:
            self.calls["search"] += 1
            key = _key(query, str(pagenum))
            rec = self._load("search", key)
            if rec:
                return SearchResult.model_validate(rec["result"])
            if not self.live:
                raise RecordingMissing(f"search not recorded: {query!r}")
            result = real_fn(query, pagenum)
            self.live_calls["search"] += 1
            self._save("search", key, {"query": query, "pagenum": pagenum, "result": result.model_dump()})
            return result

        return search

    def wrap_fetch(self, real_fn):
        def fetch(tid: int) -> DocumentText:
            self.calls["doc"] += 1
            key = str(tid)
            rec = self._load("doc", key)
            if rec:
                return DocumentText.model_validate(rec["result"])
            if not self.live:
                raise RecordingMissing(f"document not recorded: {tid}")
            result = real_fn(tid)
            self.live_calls["doc"] += 1
            self._save("doc", key, {"tid": tid, "result": result.model_dump()})
            return result

        return fetch

    def wrap_rewrite(self, real_fn):
        def rewrite(question: str, conversation_context: str | None = None) -> str:
            key = _key(question, conversation_context or "")
            if not self.fresh_rewrite:
                rec = self._load("rewrite", key)
                if rec:
                    return rec["query"]
                if not self.live:
                    raise RecordingMissing(f"rewrite not recorded: {question!r}")
            query = real_fn(question, conversation_context=conversation_context)
            # Saved even for a fresh rewrite: the latest rewrite is the one later replays should use.
            self._save("rewrite", key, {"question": question, "context": conversation_context, "query": query})
            return query

        return rewrite
