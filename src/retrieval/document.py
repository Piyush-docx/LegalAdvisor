import os

import requests
from bs4 import BeautifulSoup

from src.retrieval.schemas import DocumentText

IKANOON_BASE = "https://api.indiankanoon.org"


def fetch_document(tid: int) -> DocumentText:
    api_key = os.environ["IKANOON_API_KEY"]
    resp = requests.post(
        f"{IKANOON_BASE}/doc/{tid}/",
        headers={"Authorization": f"Token {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return DocumentText.model_validate(resp.json())


def clean_document_html(raw_html: str) -> str:
    """Strip IKanoon's HTML markup, dropping page-number artifacts
    (span.hidden_text) while keeping the substantive judgment text."""
    soup = BeautifulSoup(raw_html, "html.parser")

    for span in soup.find_all("span", class_="hidden_text"):
        span.decompose()

    text = soup.get_text(separator=" ")
    return " ".join(text.split())


# IKanoon tags paragraphs with data-structure attributes marking their role
# in the judgment. Issue/Facts/Conclusion carry the substance a citizen needs;
# CDiscource (judicial reasoning) and Precedent (citations to other cases) are
# what make full documents 100K+ chars, most of which isn't needed to explain
# the outcome in plain language -- dropping them cuts token cost by ~90%.
SUBSTANTIVE_TAGS = {"Issue", "Facts", "Conclusion"}


def extract_substantive_text(raw_html: str) -> str:
    """Extract only the Issue/Facts/Conclusion paragraphs from a judgment,
    falling back to full cleaned text if no data-structure tags are present
    (e.g. bare statute text)."""
    soup = BeautifulSoup(raw_html, "html.parser")

    for span in soup.find_all("span", class_="hidden_text"):
        span.decompose()

    tagged_paragraphs = soup.find_all(attrs={"data-structure": True})
    if not tagged_paragraphs:
        text = soup.get_text(separator=" ")
        return " ".join(text.split())

    parts = []
    for p in tagged_paragraphs:
        if p.get("data-structure") in SUBSTANTIVE_TAGS:
            t = p.get_text(separator=" ", strip=True)
            if t:
                parts.append(t)

    return " ".join(" ".join(parts).split())
