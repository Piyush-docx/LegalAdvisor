from src.llm import LLMResult


def llm_result(text="ok", stop="STOP", tokens_in=10, tokens_out=5, model="test:model") -> LLMResult:
    return LLMResult(text=text, stop_reason=stop, input_tokens=tokens_in, output_tokens=tokens_out, model=model)
