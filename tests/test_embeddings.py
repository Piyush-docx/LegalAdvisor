import math

import pytest

from src import embeddings as emb
from src.db import EMBEDDING_DIM


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture(autouse=True)
def embed_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_API_KEY", "emb-key")
    clock = FakeClock()
    monkeypatch.setattr(emb, "_now", clock.now)
    monkeypatch.setattr(emb, "_sleep", clock.sleep)
    emb.reset_state()
    yield clock
    emb.reset_state()


def raw_vector(seed=1.0):
    return [seed] + [0.0] * (EMBEDDING_DIM - 1)


def patch_api(monkeypatch, fn):
    calls = []

    def fake(texts, task):
        calls.append((list(texts), task))
        return fn(texts, task, len(calls))

    monkeypatch.setattr(emb, "_call_api", fake)
    return calls


def test_embed_query_returns_normalised_vector_and_uses_query_task(monkeypatch):
    calls = patch_api(monkeypatch, lambda texts, task, n: [[3.0, 4.0] + [0.0] * (EMBEDDING_DIM - 2)])

    vec = emb.embed_query("  my landlord keeps my deposit ")

    assert len(vec) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0)
    assert vec[0] == pytest.approx(0.6) and vec[1] == pytest.approx(0.8)
    assert calls == [(["my landlord keeps my deposit"], "RETRIEVAL_QUERY")]


def test_embed_documents_uses_document_task_and_preserves_order(monkeypatch):
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector(float(len(t))) for t in texts])

    vecs = emb.embed_documents(["a", "bb", "ccc"])

    assert [round(v[0], 3) for v in vecs] == [1.0, 1.0, 1.0]  # normalised
    assert calls[0][1] == "RETRIEVAL_DOCUMENT" and calls[0][0] == ["a", "bb", "ccc"]


def test_not_configured_raises_without_calling_api(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY")
    calls = patch_api(monkeypatch, lambda *a: [])

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q")

    assert calls == [] and emb.is_configured() is False


def test_empty_input_and_blank_text(monkeypatch):
    patch_api(monkeypatch, lambda *a: [])
    assert emb.embed_documents([]) == []
    with pytest.raises(ValueError):
        emb.embed_query("   ")


def test_batches_split_by_text_count_and_keep_order(monkeypatch):
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector() for _ in texts])

    vecs = emb.embed_documents([f"t{i}" for i in range(250)])

    assert [len(c[0]) for c in calls] == [100, 100, 50]
    assert len(vecs) == 250
    assert calls[1][0][0] == "t100"


def test_batches_split_by_token_budget(monkeypatch):
    big = "x" * 3000  # ~1000 tokens each; half-minute budget is 14000 tokens
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector() for _ in texts])

    emb.embed_documents([big] * 30)

    assert len(calls) >= 2 and all(len(c[0]) < 30 for c in calls)


def test_very_long_text_is_truncated(monkeypatch):
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector() for _ in texts])

    emb.embed_query("y" * 20000)

    assert len(calls[0][0][0]) == emb.MAX_TEXT_CHARS


def test_throttle_waits_when_token_window_is_full(monkeypatch, embed_env):
    clock = embed_env
    monkeypatch.setattr(emb, "TOKENS_PER_MINUTE", 1000)
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector() for _ in texts])
    text = "z" * 2400  # ~800 tokens

    emb.embed_documents([text])           # uses 800 of 1000
    emb.embed_documents([text])           # must wait for the first to leave the 60 s window

    assert len(calls) == 2
    assert clock.sleeps and clock.sleeps[0] == pytest.approx(60, abs=1)


def test_query_gives_up_instead_of_waiting_long(monkeypatch):
    monkeypatch.setattr(emb, "TOKENS_PER_MINUTE", 1000)
    calls = patch_api(monkeypatch, lambda texts, task, n: [raw_vector() for _ in texts])
    emb.embed_documents(["z" * 2400])

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("z" * 2400)  # would need ~60 s, query limit is 5 s

    assert len(calls) == 1


def test_rate_limit_is_retried_then_succeeds(monkeypatch, embed_env):
    def flaky(texts, task, n):
        if n == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED rate limit")
        return [raw_vector() for _ in texts]

    calls = patch_api(monkeypatch, flaky)

    vecs = emb.embed_documents(["a"])

    assert len(vecs) == 1 and len(calls) == 2 and embed_env.sleeps == [5]


def test_daily_quota_sets_long_cooldown_and_skips_network(monkeypatch):
    def dead(texts, task, n):
        raise RuntimeError("GenerateRequestsPerDayPerProjectPerModel exceeded (429)")

    calls = patch_api(monkeypatch, dead)

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q")
    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q again")

    assert len(calls) == 1  # second request never reached the API


def test_transient_error_retried_twice_then_unavailable(monkeypatch, embed_env):
    calls = patch_api(monkeypatch, lambda *a: (_ for _ in ()).throw(RuntimeError("503 UNAVAILABLE")))

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q")

    assert len(calls) == 3 and embed_env.sleeps == [1, 2]


def test_fatal_error_is_not_retried(monkeypatch):
    calls = patch_api(monkeypatch, lambda *a: (_ for _ in ()).throw(RuntimeError("400 invalid argument")))

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q")

    assert len(calls) == 1


def test_wrong_vector_shape_is_rejected(monkeypatch):
    patch_api(monkeypatch, lambda texts, task, n: [[1.0, 2.0]])

    with pytest.raises(emb.EmbeddingUnavailable):
        emb.embed_query("q")


# ---------------- provider configuration (LangChain behind _call_api) ----------------
from unittest.mock import MagicMock, patch  # noqa: E402


def test_embedding_id_identifies_provider_model_and_size(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "google_genai")
    monkeypatch.setattr(emb, "EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(emb, "EMBEDDING_DIM", 768)
    assert emb.embedding_id() == "google_genai:gemini-embedding-001:768"
    monkeypatch.setattr(emb, "EMBEDDING_MODEL", "other")
    assert emb.embedding_id() != "google_genai:gemini-embedding-001:768"


@patch("langchain.embeddings.init_embeddings")
def test_google_embedder_gets_key_model_and_output_size(mock_init, monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "google_genai")
    monkeypatch.setattr(emb, "EMBEDDING_MODEL", "gemini-embedding-001")

    emb._build_embedder()

    args, kwargs = mock_init.call_args
    assert args == ("gemini-embedding-001",)
    assert kwargs["provider"] == "google_genai" and kwargs["google_api_key"] == "emb-key"
    assert kwargs["output_dimensionality"] == EMBEDDING_DIM


@patch("langchain.embeddings.init_embeddings")
def test_openai_compatible_embedder_uses_base_url_and_dimensions(mock_init, monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(emb, "EMBEDDING_MODEL", "jina-embeddings-v3")
    monkeypatch.setattr(emb, "EMBEDDING_BASE_URL", "https://api.jina.ai/v1")

    emb._build_embedder()

    kwargs = mock_init.call_args.kwargs
    assert kwargs["provider"] == "openai" and kwargs["base_url"] == "https://api.jina.ai/v1"
    assert kwargs["dimensions"] == EMBEDDING_DIM and kwargs["api_key"] == "emb-key"


def test_unsupported_provider_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "mystery")
    with pytest.raises(emb.EmbeddingUnavailable):
        emb._build_embedder()


def test_google_call_passes_task_type_to_langchain(monkeypatch):
    fake = MagicMock()
    fake.embed_documents.return_value = [[0.1] * EMBEDDING_DIM]
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "google_genai")
    monkeypatch.setattr(emb, "_embedder", lambda: fake)

    emb._call_api(["q"], "RETRIEVAL_QUERY")

    fake.embed_documents.assert_called_once_with(["q"], task_type="RETRIEVAL_QUERY")


def test_openai_call_uses_query_and_document_methods(monkeypatch):
    fake = MagicMock()
    fake.embed_query.return_value = [0.1] * EMBEDDING_DIM
    fake.embed_documents.return_value = [[0.2] * EMBEDDING_DIM]
    monkeypatch.setattr(emb, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(emb, "_embedder", lambda: fake)

    emb._call_api(["q"], "RETRIEVAL_QUERY")
    emb._call_api(["d"], "RETRIEVAL_DOCUMENT")

    fake.embed_query.assert_called_once_with("q")
    fake.embed_documents.assert_called_once_with(["d"])
