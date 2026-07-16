"""Dev-only server that mocks answer_question so the frontend can be
click-tested end-to-end before LLM_API_KEY is added."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch

import src.api as api_module


def fake_answer_question(question: str) -> str:
    return (
        f"(mock answer for: {question!r})\n\n"
        "The security deposit must generally be refunded to the tenant "
        "once possession is handed back, subject to lawful deductions.\n\n"
        "Sources:\n"
        "- Hs Bedi vs National Highway Authority Of India: "
        "https://indiankanoon.org/doc/183757259/\n\n"
        "This is general legal information, not personalised legal advice. "
        "For anything specific to your situation, please consult a lawyer.\n\n"
        "Powered by Indian Kanoon (indiankanoon.org)."
    )


if __name__ == "__main__":
    import uvicorn

    with patch.object(api_module, "answer_question", fake_answer_question):
        uvicorn.run(api_module.app, host="127.0.0.1", port=8000)
