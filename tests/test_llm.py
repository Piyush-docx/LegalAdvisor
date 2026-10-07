from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import llm


class FakeModel:
    def __init__(self, content="ok", finish="stop", error=None, usage=None):
        self.content, self.finish, self.error = content, finish, error
        self.usage = usage if usage is not None else {"input_tokens": 7, "output_tokens": 3}
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(
            content=self.content, response_metadata={"finish_reason": self.finish}, usage_metadata=self.usage
        )


@pytest.fixture(autouse=True)
def clean_llm_state(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g-key")
    monkeypatch.setenv("LLM_API_KEY", "gem-key")
    for task in llm.DEFAULT_CHAINS:
        monkeypatch.delenv(f"LLM_CHAIN_{task.upper()}", raising=False)
    llm.reset_state()
    yield
    llm.reset_state()


def _patch_models(models: dict):
    """models: {"provider:model": FakeModel}"""
    return patch("src.llm._build_model", side_effect=lambda provider, model, mt, temp, timeout=30: models[f"{provider}:{model}"])


def test_default_chains_split_cheap_tasks_to_groq_and_answers_to_gemini():
    assert llm.chain("router")[0][0] == "groq"
    assert llm.chain("rewrite")[0][0] == "groq"
    assert llm.chain("answer")[0][0] == "google_genai"


def test_env_overrides_a_tasks_chain(monkeypatch):
    monkeypatch.setenv("LLM_CHAIN_ROUTER", "google_genai:gemini-2.5-flash")
    assert llm.chain("router") == [("google_genai", "gemini-2.5-flash")]


def test_first_model_in_chain_answers_and_usage_is_reported():
    groq, gem = FakeModel("CHITCHAT"), FakeModel("other")
    with _patch_models({"groq:openai/gpt-oss-20b": groq, "google_genai:gemini-2.5-flash": gem}):
        result = llm.complete("router", "hi")

    assert result.text == "CHITCHAT" and result.model == "groq:openai/gpt-oss-20b"
    assert (result.input_tokens, result.output_tokens, result.stop_reason) == (7, 3, "STOP")
    assert gem.calls == 0


def test_falls_back_when_first_model_errors():
    groq = FakeModel(error=RuntimeError("429 RESOURCE_EXHAUSTED"))
    gem = FakeModel("from gemini")
    with _patch_models({"groq:openai/gpt-oss-20b": groq, "google_genai:gemini-2.5-flash": gem}):
        result = llm.complete("router", "hi")

    assert result.text == "from gemini" and result.model == "google_genai:gemini-2.5-flash"


def test_rate_limited_model_is_cooled_down_and_not_retried():
    groq = FakeModel(error=RuntimeError("429 rate limit"))
    gem = FakeModel("g")
    with _patch_models({"groq:openai/gpt-oss-20b": groq, "google_genai:gemini-2.5-flash": gem}):
        llm.complete("router", "a")
        llm.complete("router", "b")

    assert groq.calls == 1  # second request skipped the cooling model
    assert gem.calls == 2


def test_daily_quota_error_gets_a_long_cooldown():
    exc = RuntimeError("GenerateRequestsPerDayPerProjectPerModel-FreeTier exceeded")
    assert llm._cooldown_seconds(exc) == 3600
    assert llm._cooldown_seconds(RuntimeError("429 rate limit")) == 60
    assert llm._cooldown_seconds(RuntimeError("503 UNAVAILABLE")) == 30
    assert llm._cooldown_seconds(RuntimeError("bad request")) == 0


def test_provider_without_api_key_is_skipped(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    gem = FakeModel("g")
    with _patch_models({"google_genai:gemini-2.5-flash": gem}):
        result = llm.complete("router", "hi")

    assert result.model == "google_genai:gemini-2.5-flash"


def test_empty_response_falls_through_to_next_model():
    groq, gem = FakeModel("   "), FakeModel("real answer")
    with _patch_models({"groq:openai/gpt-oss-20b": groq, "google_genai:gemini-2.5-flash": gem}):
        assert llm.complete("router", "hi").text == "real answer"


def test_all_models_failing_raises_with_every_reason():
    groq = FakeModel(error=RuntimeError("boom-groq"))
    gem = FakeModel(error=RuntimeError("boom-gemini"))
    with _patch_models({"groq:openai/gpt-oss-20b": groq, "google_genai:gemini-2.5-flash": gem}):
        with pytest.raises(llm.LLMUnavailable) as err:
            llm.complete("router", "hi")

    assert "boom-groq" in str(err.value) and "boom-gemini" in str(err.value)


def test_no_keys_at_all_is_unavailable_and_not_configured(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("LLM_API_KEY")
    assert llm.is_configured("router") is False
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("router", "hi")


def test_stop_reasons_are_normalised_across_providers():
    with _patch_models({"google_genai:gemini-2.5-flash": FakeModel("x", finish="MAX_TOKENS")}):
        assert llm.complete("answer", "p").stop_reason == "MAX_TOKENS"
    llm.reset_state()
    with _patch_models({"google_genai:gemini-2.5-flash": FakeModel("x", finish="length")}):
        assert llm.complete("answer", "p").stop_reason == "MAX_TOKENS"


def test_list_content_from_gemini_is_joined():
    parts = [{"type": "text", "text": "Hello "}, "world"]
    with _patch_models({"google_genai:gemini-2.5-flash": FakeModel(parts)}):
        assert llm.complete("answer", "p").text == "Hello world"


def test_reasoning_models_get_token_headroom_and_low_effort():
    llm._build_model.cache_clear()
    with patch("src.llm.init_chat_model") as init:
        llm._build_model("groq", "openai/gpt-oss-20b", 16, 0.0)
        kwargs = init.call_args.kwargs
        assert kwargs["max_tokens"] == 16 + llm.REASONING_HEADROOM
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["max_retries"] == llm.CLIENT_MAX_RETRIES and kwargs["timeout"] == 30

        llm._build_model("google_genai", "gemini-2.5-flash", 64, 0.0)
        kwargs = init.call_args.kwargs
        assert kwargs["max_tokens"] == 64 and kwargs["thinking_budget"] == 0
    llm._build_model.cache_clear()


def test_each_task_gets_its_own_timeout_and_a_single_client_retry():
    seen = {}

    def build(provider, model, mt, temp, timeout=30):
        seen[provider] = timeout
        return FakeModel("ok")

    with patch("src.llm._build_model", side_effect=build):
        llm.complete("router", "x")
        router_timeout = seen["groq"]
        llm.reset_state()
        llm.complete("answer", "x")

    assert router_timeout == llm.TASK_TIMEOUTS["router"] < seen["google_genai"] == llm.TASK_TIMEOUTS["answer"]
    assert llm.CLIENT_MAX_RETRIES <= 1
