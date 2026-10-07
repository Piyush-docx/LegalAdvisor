import json

import time

from src.db import cache_query, get_cached_query, log_query, using_postgres
from src.generation.generate import explain_with_llm
from src.generation.safety import attach_disclaimer_and_attribution
from src.guardrails import (
    apply_output_guardrails,
    budget_response,
    clarify_response,
    decline_response,
    detect_harm,
    harm_response,
    ikanoon_budget,
    is_prompt_attack,
    no_sources_response,
    out_of_scope_response,
    process_citations,
    redact_pii,
)
from src.retrieval.context import BudgetExceeded, Citation, build_context
from src.retrieval.indexer import index_answer, run_in_background
from src.retrieval.tiers import find_followup_context, find_reviewed_answer, find_stored_context, question_vector
from src.retrieval.rewrite import rewrite_query
from src.router import (
    RouteIntent,
    can_context_answer_followup,
    classify_intent,
    format_conversation_summary,
    generate_chitchat_response,
)
from src.session import AnswerWithSession, SessionStore, default_session_store

_CANNED = {
    RouteIntent.OUT_OF_SCOPE: out_of_scope_response,
    RouteIntent.DECLINE: decline_response,
    RouteIntent.CLARIFY: clarify_response,
    RouteIntent.HARM: lambda: harm_response(None),
}


def _retrieve(search_query: str, question: str, flags: list[str], info: dict | None = None):
    """Run IKanoon retrieval under the daily budget.

    Returns (context_text, citations, canned_reply, weak_sources). canned_reply is set instead of an answer
    when the budget is spent or nothing usable was found; the LLM is not called in either case.
    weak_sources means a law was asked for by name but its title was not found, so the sources that were
    used (from the topic query) may not be the main law."""
    info = info if info is not None else {}
    try:
        context_text, citations = build_context(
            search_query, question=question, consume=ikanoon_budget.consume, info=info
        )
    except BudgetExceeded:
        flags.append("budget_exceeded")
        return "", [], budget_response(), False
    if info.get("relaxed"):
        flags.append("query_relaxed")
    if not context_text.strip():
        flags.append("no_sources")
        return "", [], no_sources_response(), False
    return context_text, citations, None, bool(info.get("act_requested") and not info.get("act_matched"))


def _finalize(
    answer_text: str, context_text: str, citations: list[Citation], question: str, flags: list[str],
    weak_sources: bool = False,
) -> str:
    """Validate [n] citations, apply output guardrails, and attach the sources, disclaimer and attribution."""
    text, cited, cite_flags = process_citations(answer_text, len(citations))
    text, out_flags = apply_output_guardrails(text, context_text, question, weak_sources=weak_sources)
    flags += cite_flags + out_flags
    return attach_disclaimer_and_attribution(text, citations, cited or None)


def _answer_from_store(question: str, vec: list[float], flags: list[str]):
    """Tiers 1 and 2. Returns (final_answer, context_text, citations, was_cached) or None for the cold path."""
    reviewed = find_reviewed_answer(vec)
    if reviewed:
        stored_answer, context_text, citations = reviewed
        flags.append("tier:cache")
        return _finalize(stored_answer, context_text, citations, question, flags), context_text, citations, True

    stored = find_stored_context(vec)
    if stored:
        context_text, citations, kind = stored
        flags.append(f"tier:{kind}")
        answer = explain_with_llm(question, context_text, citations, history=None)
        if not getattr(answer, "truncated", False) is True:
            citations_json = json.dumps([c.model_dump() for c in citations])
            run_in_background(index_answer, question, vec, answer.text, context_text, citations_json, [])
        return _finalize(answer.text, context_text, citations, question, flags), context_text, citations, False
    return None


def answer_question(
    question: str,
    session_id: str | None = None,
    return_session: bool = False,
    session_store: SessionStore | None = None,
    user_id: str | None = None,
) -> str | tuple[str, str]:
    start_time = time.perf_counter()
    was_cached = False
    flags: list[str] = []

    # Everything downstream (LLM prompts, cache keys, logs, stored history) sees the redacted text.
    redacted = redact_pii(question)
    if redacted != question:
        flags.append("pii_redacted")
    question = redacted

    store = session_store or default_session_store
    session = store.get_or_create(session_id, user_id=user_id)

    # Safety checks that need no LLM run first, so they still work when providers are down.
    harm = detect_harm(question)
    if harm:
        intent = RouteIntent.HARM
        flags.append(f"harm:{harm.value}")
        final_answer = harm_response(harm)
    elif is_prompt_attack(question):
        intent = RouteIntent.DECLINE
        flags.append("prompt_attack")
        final_answer = decline_response()
    else:
        intent = classify_intent(question, session)
        final_answer = None

    if final_answer is not None:
        pass  # keyword guardrail already produced the reply

    elif intent in _CANNED:
        flags.append(f"intent:{intent.name}")
        final_answer = _CANNED[intent]()

    elif intent == RouteIntent.CHITCHAT:
        final_answer = generate_chitchat_response(question)

    elif intent == RouteIntent.FOLLOW_UP and session.last_context_text:
        # E3: a follow-up is usually answerable from the stored chunks of the documents just cited.
        vec = question_vector(question, flags)
        followup = find_followup_context(vec, session.last_citations) if vec is not None else None
        if followup:
            context_text, citations = followup
            flags.append("tier:followup")
            answer = explain_with_llm(question, context_text, citations, history=session.messages)
            final_answer = _finalize(answer.text, context_text, citations, question, flags)
            session.last_context_text, session.last_citations = context_text, citations
        elif can_context_answer_followup(question, session.last_context_text):
            answer = explain_with_llm(
                question,
                session.last_context_text,
                session.last_citations,
                history=session.messages,
            )
            final_answer = _finalize(answer.text, session.last_context_text, session.last_citations, question, flags)
        else:
            # Context insufficient for follow-up: blend conversation history for new retrieval
            conversation_context = format_conversation_summary(session)
            search_query = rewrite_query(question, conversation_context=conversation_context)
            context_text, citations, canned, weak = _retrieve(search_query, question, flags)
            if canned:
                final_answer = canned
            else:
                session.last_context_text = context_text
                session.last_citations = citations
                session.last_query = question

                answer = explain_with_llm(
                    question, context_text, citations, history=session.messages
                )
                final_answer = _finalize(answer.text, context_text, citations, question, flags, weak_sources=weak)

    else:
        # NEW_QUERY or initial query
        update_session_context = True
        vec = question_vector(question, flags)  # None unless PostgreSQL + embeddings are available
        from_store = _answer_from_store(question, vec, flags) if vec is not None else None

        if from_store:
            final_answer, context_text, citations, was_cached = from_store
        else:
            search_query = rewrite_query(question)

            # --- CACHE CHECK ---
            cached = get_cached_query(search_query)
            if cached:
                was_cached = True
                context_text = cached["context_text"]
                citations_data = json.loads(cached["citations"])
                citations = [Citation(**c) for c in citations_data]
                llm_answer = cached["llm_answer"]
                final_answer = _finalize(llm_answer, context_text, citations, question, flags)
            else:
                retrieval_info: dict = {}
                context_text, citations, canned, weak = _retrieve(search_query, question, flags, retrieval_info)
                if vec is not None or using_postgres():
                    flags.append("tier:cold")
                if canned:
                    final_answer = canned
                    update_session_context = False
                else:
                    # A NEW_QUERY is an independent question, so no conversation history is passed.
                    # The answer is cached and served to other users; it must not carry this user's chat.
                    answer = explain_with_llm(question, context_text, citations, history=None)
                    llm_answer = answer.text

                    # Only cache answers that are safe to reuse: grounded in retrieved text and complete.
                    # The cache holds the raw answer; output notes are applied at serve time.
                    truncated = getattr(answer, "truncated", False) is True
                    if context_text.strip() and not truncated and not weak:
                        citations_json = json.dumps([c.model_dump() for c in citations])
                        cache_query(search_query, context_text, citations_json, llm_answer)
                        if vec is not None:  # weak (maybe wrong-Act) chunks are never stored for reuse
                            run_in_background(index_answer, question, vec, llm_answer, context_text,
                                              citations_json, retrieval_info.get("chunks", []))

                    final_answer = _finalize(llm_answer, context_text, citations, question, flags, weak_sources=weak)

        if update_session_context:
            session.last_context_text = context_text
            session.last_citations = citations
            session.last_query = question

    session.add_message("user", question)
    session.add_message("assistant", final_answer)
    store.save(session)

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    log_query(question, intent.name, was_cached, duration_ms, guardrails=",".join(flags))

    if return_session:
        return final_answer, session.session_id
    return AnswerWithSession(final_answer, session.session_id)
