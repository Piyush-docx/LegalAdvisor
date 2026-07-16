import os

from google import genai
from google.genai import types

from src.generation.prompt import build_prompt
from src.generation.schemas import LLMAnswer, Usage
from src.retrieval.context import Citation

MODEL = "gemini-2.5-flash"


def explain_with_llm(question: str, context_text: str, citations: list[Citation]) -> LLMAnswer:
    api_key = os.environ["LLM_API_KEY"]
    client = genai.Client(api_key=api_key)

    prompt = build_prompt(question, context_text, citations)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    if not response.text:
        candidate = response.candidates[0] if response.candidates else None
        finish_reason = candidate.finish_reason if candidate else None
        raise ValueError(f"No text content in LLM response (finish_reason={finish_reason!r})")

    candidate = response.candidates[0]
    return LLMAnswer(
        text=response.text,
        stop_reason=candidate.finish_reason.name if candidate.finish_reason else "STOP",
        usage=Usage(
            input_tokens=response.usage_metadata.prompt_token_count or 0,
            output_tokens=response.usage_metadata.candidates_token_count or 0,
        ),
    )
