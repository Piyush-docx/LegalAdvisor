"""Hosted embedding API client (Gemini), the single entry point for turning text into vectors.

Why this exists as its own module: embeddings have their own provider key, quota and failure modes.
The key is EMBEDDING_API_KEY, deliberately separate from LLM_API_KEY, and should come from a different
Google project (quotas are per project), so answer generation never competes with it.

The provider is configuration, not code: EMBEDDING_PROVIDER (google_genai | openai), EMBEDDING_MODEL,
EMBEDDING_DIM, optionally EMBEDDING_BASE_URL for OpenAI-compatible services. LangChain talks to the
provider. Switching models still means re-embedding stored vectors; every stored vector records the
model that made it (embedding_id()) and `python3 -m scripts.reembed` migrates them.

Rules baked in:
  * One model per index. Vectors from different models are not comparable, so there is no
    cross-model fallback. If this service is unavailable callers get EmbeddingUnavailable and must
    take the non-vector path (IKanoon search); a request must never fail because of embeddings.
  * Free tier is 30,000 tokens/min and 100 requests/min, so calls are throttled client-side.
  * Output is truncated to EMBEDDING_DIM (see src/db.py) and L2-normalised.
  * Questions use task type RETRIEVAL_QUERY (also for stored questions in the answer cache, so both
    sides of a comparison are embedded the same way); chunks use RETRIEVAL_DOCUMENT.
"""

import logging
import math
import os
import threading
import time
from collections import deque

from src.db import EMBEDDING_DIM

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "google_genai")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL")
# Stay under the free-tier limits (30,000 tokens/min, 100 requests/min) with a margin.
TOKENS_PER_MINUTE = int(os.environ.get("EMBEDDING_TPM", "28000"))
REQUESTS_PER_MINUTE = int(os.environ.get("EMBEDDING_RPM", "90"))
MAX_TEXTS_PER_CALL = 100
MAX_TEXT_CHARS = 6000  # the model accepts 2048 tokens per input; ~3 chars/token is a safe estimate
QUERY_MAX_WAIT_SECONDS = 5.0  # never make a user wait on the embedding quota for longer than this

# Patched in tests.
_now = time.monotonic
_sleep = time.sleep


class EmbeddingUnavailable(Exception):
    """Embeddings cannot be produced right now (not configured, quota, outage). Use the non-vector path."""


def is_configured() -> bool:
    return bool(os.environ.get("EMBEDDING_API_KEY"))


def embedding_id() -> str:
    """Identifies the vector space. Vectors are only comparable when this string is identical."""
    return f"{EMBEDDING_PROVIDER}:{EMBEDDING_MODEL}:{EMBEDDING_DIM}"


def estimate_tokens(text: str) -> int:
    return len(text) // 3 + 1


# ----------------------------------------------------------------------------------- throttling
class _Throttle:
    """Sliding 60 s window over both tokens and requests."""

    def __init__(self):
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._events and self._events[0][0] <= now - 60:
            self._events.popleft()

    def wait_needed(self, tokens: int) -> float:
        """Seconds to wait before `tokens` fit in the window (0 = now)."""
        tokens = min(tokens, TOKENS_PER_MINUTE)  # a single oversized batch must still be able to pass
        with self._lock:
            now = _now()
            self._prune(now)
            used = sum(t for _, t in self._events)
            count = len(self._events)
            if used + tokens <= TOKENS_PER_MINUTE and count + 1 <= REQUESTS_PER_MINUTE:
                return 0.0
            # Wait for enough old events to expire.
            freed, need_tokens, need_slot = 0, used + tokens - TOKENS_PER_MINUTE, count + 1 - REQUESTS_PER_MINUTE
            for i, (ts, t) in enumerate(self._events, 1):
                freed += t
                if freed >= need_tokens and i >= need_slot:
                    return max(0.0, ts + 60 - now)
            return 60.0

    def record(self, tokens: int) -> None:
        with self._lock:
            self._events.append((_now(), min(tokens, TOKENS_PER_MINUTE)))

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_throttle = _Throttle()
_cooldown_until = 0.0


# ----------------------------------------------------------------------------------- API call
_embedder_obj = None
_embedder_lock = threading.Lock()


def _build_embedder():
    """Create the LangChain embeddings object for the configured provider."""
    from langchain.embeddings import init_embeddings

    key = os.environ["EMBEDDING_API_KEY"]
    if EMBEDDING_PROVIDER == "google_genai":
        return init_embeddings(
            EMBEDDING_MODEL, provider="google_genai", google_api_key=key, output_dimensionality=EMBEDDING_DIM
        )
    if EMBEDDING_PROVIDER == "openai":  # also any OpenAI-compatible endpoint via EMBEDDING_BASE_URL
        kwargs = {"api_key": key, "dimensions": EMBEDDING_DIM}
        if EMBEDDING_BASE_URL:
            kwargs["base_url"] = EMBEDDING_BASE_URL
        return init_embeddings(EMBEDDING_MODEL, provider="openai", **kwargs)
    raise EmbeddingUnavailable(f"unsupported EMBEDDING_PROVIDER {EMBEDDING_PROVIDER!r}")


def _embedder():
    global _embedder_obj
    with _embedder_lock:
        if _embedder_obj is None:
            _embedder_obj = _build_embedder()
        return _embedder_obj


def _call_api(texts: list[str], task: str) -> list[list[float]]:
    """The only function that touches the network (patched in tests)."""
    embedder = _embedder()
    if EMBEDDING_PROVIDER == "google_genai":
        # Gemini embeds questions and passages differently; ask for the right task type.
        return [list(v) for v in embedder.embed_documents(texts, task_type=task)]
    if task == "RETRIEVAL_QUERY":
        return [list(embedder.embed_query(t)) for t in texts]
    return [list(v) for v in embedder.embed_documents(texts)]


def reset_state() -> None:
    """Clear throttle, cooldown and the cached embedder (used by tests and after config changes)."""
    global _cooldown_until, _embedder_obj
    _throttle.reset()
    _cooldown_until = 0.0
    _embedder_obj = None


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def _error_kind(exc: Exception) -> str:
    text = repr(exc).lower().replace("_", "").replace(" ", "")
    if "perday" in text:
        return "daily_quota"
    if any(s in text for s in ("429", "resourceexhausted", "quota", "ratelimit")):
        return "rate_limit"
    if any(s in text for s in ("503", "500", "unavailable", "overloaded", "timeout", "timedout", "connect")):
        return "transient"
    return "fatal"


def _embed_batch(texts: list[str], task: str, deadline: float) -> list[list[float]]:
    global _cooldown_until
    tokens = sum(estimate_tokens(t) for t in texts)
    attempt = 0
    while True:
        if _now() < _cooldown_until:
            raise EmbeddingUnavailable("embedding quota is cooling down")

        wait = _throttle.wait_needed(tokens)
        if wait > 0:
            if _now() + wait > deadline:
                raise EmbeddingUnavailable(f"embedding throttle: would need to wait {wait:.0f}s")
            _sleep(wait)
            continue

        _throttle.record(tokens)
        try:
            vectors = _call_api(texts, task)
        except Exception as exc:  # noqa: BLE001
            kind = _error_kind(exc)
            if kind == "daily_quota":
                _cooldown_until = _now() + 3600
                raise EmbeddingUnavailable("daily embedding quota exhausted") from exc
            if kind == "rate_limit" and attempt < 3:
                backoff = 5 * (attempt + 1)
                if _now() + backoff <= deadline:
                    attempt += 1
                    logger.warning("embedding rate limited; retrying in %ss", backoff)
                    _sleep(backoff)
                    continue
                _cooldown_until = _now() + 60
                raise EmbeddingUnavailable("embedding rate limited") from exc
            if kind == "transient" and attempt < 2:
                attempt += 1
                _sleep(attempt)
                continue
            logger.error("embedding call failed (%s): %s", kind, str(exc)[:200])
            raise EmbeddingUnavailable(f"embedding call failed: {str(exc)[:120]}") from exc

        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
            raise EmbeddingUnavailable("embedding API returned an unexpected shape")
        return [_normalise(v) for v in vectors]


def _batches(texts: list[str]):
    """Split into calls of at most MAX_TEXTS_PER_CALL texts and half a minute of token budget."""
    budget = TOKENS_PER_MINUTE // 2
    batch, used = [], 0
    for text in texts:
        t = estimate_tokens(text)
        if batch and (len(batch) >= MAX_TEXTS_PER_CALL or used + t > budget):
            yield batch
            batch, used = [], 0
        batch.append(text)
        used += t
    if batch:
        yield batch


def _prepare(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("cannot embed empty text")
    if len(text) > MAX_TEXT_CHARS:
        logger.warning("truncating text of %d chars to %d for embedding", len(text), MAX_TEXT_CHARS)
        text = text[:MAX_TEXT_CHARS]
    return text


def embed_texts(texts: list[str], kind: str, max_wait_seconds: float) -> list[list[float]]:
    """Embed `texts` in order. kind is 'query' or 'document'."""
    if kind not in ("query", "document"):
        raise ValueError("kind must be 'query' or 'document'")
    if not texts:
        return []
    if not is_configured():
        raise EmbeddingUnavailable("EMBEDDING_API_KEY is not set")
    prepared = [_prepare(t) for t in texts]
    task = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
    deadline = _now() + max_wait_seconds
    out: list[list[float]] = []
    for batch in _batches(prepared):
        out.extend(_embed_batch(batch, task, deadline))
    return out


def embed_query(text: str) -> list[float]:
    """Embed one question for answer-cache or chunk search. Waits at most QUERY_MAX_WAIT_SECONDS."""
    return embed_texts([text], "query", QUERY_MAX_WAIT_SECONDS)[0]


def embed_documents(texts: list[str], max_wait_seconds: float = 300.0) -> list[list[float]]:
    """Embed chunks (background work, so it may wait for quota for a few minutes)."""
    return embed_texts(texts, "document", max_wait_seconds)
