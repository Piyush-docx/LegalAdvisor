"""Single entry point for every LLM call in the app.

Callers name a *task* (router, context_check, rewrite, answer); this module decides which model
serves it. Each task has an ordered chain of ``provider:model`` entries, tried in order, so a
rate-limited or overloaded provider falls through to the next one. Cheap classification tasks
default to Groq so the (tightly quota-limited) Gemini key is spent on final answers.

Override a task's chain without touching code:
    LLM_CHAIN_ROUTER="groq:openai/gpt-oss-20b,google_genai:gemini-2.5-flash"
Keys: Gemini = LLM_API_KEY (or GOOGLE_API_KEY), Groq = GROQ_API_KEY.

Fallback is a plain loop over LangChain chat models (not RunnableWithFallbacks) so we know which
model actually answered and can put a failing one on a short cooldown instead of paying its
timeout on every request.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache

from langchain.chat_models import init_chat_model

logger = logging.getLogger(__name__)

GEMINI = "google_genai:gemini-2.5-flash"
DEFAULT_CHAINS = {
    "router": f"groq:openai/gpt-oss-20b,{GEMINI}",
    "context_check": f"groq:openai/gpt-oss-20b,{GEMINI}",
    "rewrite": f"groq:openai/gpt-oss-120b,{GEMINI}",
    "answer": f"{GEMINI},groq:openai/gpt-oss-120b",
}

# Seconds a single call may take before we give up and try the next model, and how often the client
# library may retry on its own. The library default (several retries with growing waits) turned one
# rate-limited call into ~45 s before our fallback even started.
TASK_TIMEOUTS = {"router": 15, "context_check": 15, "rewrite": 20, "answer": 60}
CLIENT_MAX_RETRIES = 1

# gpt-oss / qwen3 spend part of max_tokens on hidden reasoning; without headroom a short
# classification call comes back empty (finish_reason=length).
REASONING_HEADROOM = 512
_REASONING_MODELS = ("gpt-oss", "qwen3")

_KEY_ENV = {"groq": ("GROQ_API_KEY",), "google_genai": ("LLM_API_KEY", "GOOGLE_API_KEY")}


class LLMUnavailable(Exception):
    """Every model in the task's chain failed or is not configured."""


@dataclass
class LLMResult:
    text: str
    stop_reason: str  # "STOP" or "MAX_TOKENS" (other provider values passed through upper-cased)
    input_tokens: int
    output_tokens: int
    model: str  # the "provider:model" that actually answered


def _parse(spec: str) -> tuple[str, str]:
    provider, _, model = spec.strip().partition(":")
    return provider, model


def chain(task: str) -> list[tuple[str, str]]:
    raw = os.environ.get(f"LLM_CHAIN_{task.upper()}") or DEFAULT_CHAINS[task]
    return [_parse(s) for s in raw.split(",") if s.strip()]


def describe() -> dict[str, str]:
    """Task -> chain string, for eval reports."""
    return {task: ",".join(f"{p}:{m}" for p, m in chain(task)) for task in DEFAULT_CHAINS}


def _api_key(provider: str) -> str | None:
    for name in _KEY_ENV.get(provider, ()):
        if os.environ.get(name):
            return os.environ[name]
    return None


def is_configured(task: str) -> bool:
    return any(_api_key(p) for p, _ in chain(task))


@lru_cache(maxsize=64)
def _build_model(provider: str, model: str, max_tokens: int, temperature: float, timeout: float = 30):
    kwargs = {
        "model_provider": provider, "temperature": temperature, "api_key": _api_key(provider),
        "timeout": timeout, "max_retries": CLIENT_MAX_RETRIES,
    }
    if provider == "google_genai":
        kwargs.update(max_tokens=max_tokens, thinking_budget=0)
    else:
        reasoning = any(m in model for m in _REASONING_MODELS)
        kwargs["max_tokens"] = max_tokens + (REASONING_HEADROOM if reasoning else 0)
        if "gpt-oss" in model:
            kwargs["reasoning_effort"] = "low"
    return init_chat_model(model, **kwargs)


# --- cooldowns: stop sending traffic to a model that just told us it is out of quota ---------
_cooldown_until: dict[str, tuple[float, int]] = {}  # spec -> (until, seconds)
_lock = threading.Lock()


def _cooldown_seconds(exc: Exception) -> int:
    text = repr(exc).lower().replace("_", "").replace(" ", "")
    if "perday" in text or "tpd" in text:
        return 3600
    if any(s in text for s in ("429", "ratelimit", "quota", "resourceexhausted")):
        return 60
    if any(s in text for s in ("503", "unavailable", "overloaded")):
        return 30
    return 0


def _cooling(spec: str) -> bool:
    with _lock:
        return _cooldown_until.get(spec, (0.0, 0))[0] > time.monotonic()


def _cooling_reason(spec: str) -> str:
    with _lock:
        return "cooling down (daily limit)" if _cooldown_until.get(spec, (0.0, 0))[1] >= 3600 else "cooling down"


def _cool(spec: str, exc: Exception) -> None:
    seconds = _cooldown_seconds(exc)
    if seconds:
        with _lock:
            _cooldown_until[spec] = (time.monotonic() + seconds, seconds)


def reset_state() -> None:
    with _lock:
        _cooldown_until.clear()
    _build_model.cache_clear()


def _text(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        part if isinstance(part, str) else part.get("text", "") for part in content if part
    )


def _stop_reason(message) -> str:
    raw = str((message.response_metadata or {}).get("finish_reason") or "STOP").upper()
    return "MAX_TOKENS" if raw in ("LENGTH", "MAX_TOKENS") else raw


def complete(task: str, prompt: str, max_tokens: int = 256, temperature: float = 0.0) -> LLMResult:
    """Run `prompt` on the first healthy model in the task's chain."""
    errors: list[str] = []
    for provider, model in chain(task):
        spec = f"{provider}:{model}"
        if not _api_key(provider):
            errors.append(f"{spec}: no API key")
            continue
        if _cooling(spec):
            errors.append(f"{spec}: {_cooling_reason(spec)}")
            continue
        try:
            message = _build_model(provider, model, max_tokens, temperature, TASK_TIMEOUTS.get(task, 30)).invoke(prompt)
            text = _text(message)
            if not text.strip():
                raise ValueError(f"empty response (finish_reason={_stop_reason(message)})")
        except Exception as exc:  # noqa: BLE001 - any provider failure should fall through
            _cool(spec, exc)
            logger.warning("LLM task %r: %s failed (%s); trying next model", task, spec, str(exc)[:200])
            errors.append(f"{spec}: {str(exc)[:300]}")
            continue
        usage = message.usage_metadata or {}
        return LLMResult(
            text=text,
            stop_reason=_stop_reason(message),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            model=spec,
        )
    raise LLMUnavailable(f"no model available for task {task!r}: " + "; ".join(errors))
