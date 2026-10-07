import logging
import os
import re

from src.generation.prompt import build_prompt
from src.generation.schemas import LLMAnswer, Usage
from src.llm import complete
from src.retrieval.context import Citation

logger = logging.getLogger(__name__)

# 1024 used to cut detailed answers off mid-sentence; stop_reason is now checked as well.
MAX_OUTPUT_TOKENS = int(os.environ.get("ANSWER_MAX_OUTPUT_TOKENS", "4096"))
# Low but not zero: stable wording for a shared cache, without flat repetition.
ANSWER_TEMPERATURE = float(os.environ.get("ANSWER_TEMPERATURE", "0.2"))
TRUNCATION_NOTE = "(This answer was shortened. Ask a follow-up question for more detail.)"

def trim_incomplete(text: str) -> str:
    """Cut a token-capped answer back to its last complete sentence or line."""
    text = text.rstrip()
    matches = list(re.finditer(r"[.!?\u0964:)](?=\s|$)|\n", text))
    if not matches:
        return text
    return text[: matches[-1].end()].rstrip()


def explain_with_llm(
    question: str,
    context_text: str,
    citations: list[Citation],
    history: list | None = None,
) -> LLMAnswer:
    prompt = build_prompt(question, context_text, citations, history=history)
    result = complete("answer", prompt, max_tokens=MAX_OUTPUT_TOKENS, temperature=ANSWER_TEMPERATURE)

    text = result.text
    truncated = result.stop_reason == "MAX_TOKENS"
    if truncated:
        logger.warning("LLM answer hit max_output_tokens=%s; trimming to last complete sentence", MAX_OUTPUT_TOKENS)
        text = f"{trim_incomplete(text)}\n\n{TRUNCATION_NOTE}"
    return LLMAnswer(
        text=text,
        stop_reason=result.stop_reason,
        truncated=truncated,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
    )
