import json
from pathlib import Path

import pytest
import responses

from src.retrieval.search import search_ikanoon
from src.retrieval.schemas import SearchResult

FIXTURES = Path(__file__).parent / "fixtures"


@responses.activate
def test_search_ikanoon_returns_validated_search_result():
    fixture = json.loads((FIXTURES / "search_response.json").read_text())
    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=fixture,
        status=200,
    )

    result = search_ikanoon("security deposit refund tenant landlord")

    assert isinstance(result, SearchResult)
    assert len(result.docs) == 10
    assert result.docs[0].title.startswith("Hs Bedi")


@responses.activate
def test_search_ikanoon_sends_token_auth_header():
    fixture = json.loads((FIXTURES / "search_response.json").read_text())
    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json=fixture,
        status=200,
    )

    search_ikanoon("security deposit refund tenant landlord")

    sent_request = responses.calls[0].request
    assert sent_request.headers["Authorization"].startswith("Token ")


@responses.activate
def test_search_ikanoon_raises_on_malformed_response():
    responses.add(
        responses.POST,
        "https://api.indiankanoon.org/search/",
        json={"unexpected": "shape"},
        status=200,
    )

    with pytest.raises(Exception):
        search_ikanoon("anything")
