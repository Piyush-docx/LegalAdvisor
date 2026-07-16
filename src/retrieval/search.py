import os

import requests

from src.retrieval.schemas import SearchResult

IKANOON_BASE = "https://api.indiankanoon.org"


def search_ikanoon(query: str, pagenum: int = 0) -> SearchResult:
    api_key = os.environ["IKANOON_API_KEY"]
    resp = requests.post(
        f"{IKANOON_BASE}/search/",
        headers={"Authorization": f"Token {api_key}"},
        data={"formInput": query, "pagenum": pagenum},
        timeout=30,
    )
    resp.raise_for_status()
    return SearchResult.model_validate(resp.json())
