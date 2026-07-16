from src.generation.generate import explain_with_llm
from src.generation.safety import attach_disclaimer_and_attribution
from src.retrieval.context import build_context


def answer_question(question: str) -> str:
    context_text, citations = build_context(question)
    answer = explain_with_llm(question, context_text, citations)
    return attach_disclaimer_and_attribution(answer.text, citations)
