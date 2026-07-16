import pytest


@pytest.fixture(autouse=True)
def ikanoon_api_key(monkeypatch):
    monkeypatch.setenv("IKANOON_API_KEY", "test-key-for-tests")
