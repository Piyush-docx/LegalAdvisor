from src.retrieval.context import Citation


def build_prompt(
    question: str,
    context_text: str,
    citations: list[Citation],
    history: list | None = None,
) -> str:
    citation_list = "\n".join(f"- {c.title}: {c.url}" for c in citations)

    history_block = ""
    if history:
        turns = []
        for m in history[-4:]:
            role = m.role if hasattr(m, "role") else m.get("role", "user")
            content = m.content if hasattr(m, "content") else m.get("content", "")
            turns.append(f"{role.capitalize()}: {content}")
        if turns:
            history_block = f"PRIOR CONVERSATION HISTORY:\n" + "\n".join(turns) + "\n\n"

    return f"""You help ordinary Indian citizens understand the law. Answer the
QUESTION below in plain, simple language. Use your general knowledge of Indian 
law to provide a comprehensive answer, and use the RETRIEVED TEXT as supportive 
references and examples.

How to answer:
- Start with a direct answer to what the person actually asked — the bottom
  line first, in one or two sentences. Do not open with commentary about what
  the retrieved text does or doesn't contain.
- Then explain what the law generally says across India and the general process 
  the person can follow.
- If the RETRIEVED TEXT contains state-specific laws or cases, mention that 
  laws may vary by state and use the retrieved texts as examples (e.g., "For 
  example, in Tamil Nadu...").
- Cite the source when you pull specific claims or examples from the RETRIEVED 
  TEXT (name the Act/section or case).
- Explain the law and general process only — never give personalised legal
  advice about what the specific person should do in their exact case.

{history_block}RETRIEVED TEXT:
{context_text}

AVAILABLE SOURCES:
{citation_list}

QUESTION: {question}"""
