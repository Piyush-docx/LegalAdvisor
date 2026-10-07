import json

import time

from src.db import cache_query, get_cached_query, log_query
from src.generation.generate import explain_with_llm
from src.generation.safety import attach_disclaimer_and_attribution
from src.retrieval.context import Citation, build_context
from src.retrieval.rewrite import rewrite_query
from src.router import (
    RouteIntent,
    can_context_answer_followup,
    classify_intent,
    format_conversation_summary,
    generate_chitchat_response,
)
from src.session import AnswerWithSession, SessionStore, default_session_store


def answer_question(
    question: str,
    session_id: str | None = None,
    return_session: bool = False,
    session_store: SessionStore | None = None,
    user_id: str | None = None,
) -> str | tuple[str, str]:
    start_time = time.perf_counter()
    was_cached = False
    
    store = session_store or default_session_store
    session = store.get_or_create(session_id, user_id=user_id)

    intent = classify_intent(question, session)

    if intent == RouteIntent.CHITCHAT:
        final_answer = generate_chitchat_response(question)

    elif intent == RouteIntent.FOLLOW_UP and session.last_context_text:
        if can_context_answer_followup(question, session.last_context_text):
            answer = explain_with_llm(
                question,
                session.last_context_text,
                session.last_citations,
                history=session.messages,
            )
            final_answer = attach_disclaimer_and_attribution(
                answer.text, session.last_citations
            )
        else:
            # Context insufficient for follow-up: blend conversation history for new retrieval
            conversation_context = format_conversation_summary(session)
            search_query = rewrite_query(question, conversation_context=conversation_context)
            context_text, citations = build_context(search_query)
            session.last_context_text = context_text
            session.last_citations = citations
            session.last_query = question

            answer = explain_with_llm(
                question, context_text, citations, history=session.messages
            )
            final_answer = attach_disclaimer_and_attribution(answer.text, citations)

    else:
        # NEW_QUERY or initial query
        search_query = rewrite_query(question)
        
        # --- CACHE CHECK ---
        cached = get_cached_query(search_query)
        if cached:
            was_cached = True
            context_text = cached["context_text"]
            citations_data = json.loads(cached["citations"])
            citations = [Citation(**c) for c in citations_data]
            llm_answer = cached["llm_answer"]
            final_answer = attach_disclaimer_and_attribution(llm_answer, citations)
        else:
            context_text, citations = build_context(search_query)
            answer = explain_with_llm(
                question, context_text, citations, history=session.messages
            )
            llm_answer = answer.text
            final_answer = attach_disclaimer_and_attribution(llm_answer, citations)
            
            # Save to cache
            citations_json = json.dumps([c.model_dump() for c in citations])
            cache_query(search_query, context_text, citations_json, llm_answer)

        session.last_context_text = context_text
        session.last_citations = citations
        session.last_query = question

    session.add_message("user", question)
    session.add_message("assistant", final_answer)
    store.save(session)

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    log_query(question, intent.name, was_cached, duration_ms)

    if return_session:
        return final_answer, session.session_id
    return AnswerWithSession(final_answer, session.session_id)
