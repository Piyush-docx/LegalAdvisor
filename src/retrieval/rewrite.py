import os

from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"

REWRITE_PROMPT = """\
You convert a citizen's everyday legal question into a search query for \
Indian Kanoon, a keyword search engine over Indian statutes and case law.

Rules:
- Output ONLY the search query, nothing else.
- Format: one quoted legal phrase, then ANDD, then one or two single-word \
terms. ANDD (double D) is Indian Kanoon's AND operator.
- One of the terms MUST name the area of law, so results stay on topic: \
tenancy for landlord/tenant issues, employment, marriage, consumer, motor, \
property, etc. E.g. for a deposit dispute with a landlord: "security \
deposit" ANDD tenancy ANDD refund — never just "security deposit" ANDD \
refund, which matches contractor and government deposits too.
- Drop all personal details, amounts, and numbers from the question.
- Use the legal terms of art an Indian lawyer would use (e.g. "security \
deposit", "eviction", "gratuity", "maintenance").
- Append doctypes: laws to the end of the query so statutes are searched \
instead of judgments. Only omit it when the person is asking how courts \
have decided cases like theirs.

Question: {question}
"""


def rewrite_query(question: str) -> str:
    api_key = os.environ["LLM_API_KEY"]
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL,
        contents=REWRITE_PROMPT.format(question=question),
        config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    query = (response.text or "").strip()
    return query or question
