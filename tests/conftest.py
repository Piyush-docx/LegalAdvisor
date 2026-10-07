import pytest

import src.db


@pytest.fixture(autouse=True)
def ikanoon_api_key(monkeypatch):
    monkeypatch.setenv("IKANOON_API_KEY", "test-key-for-tests")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite file so nothing writes to the real legal.db."""
    # Unit tests always run on SQLite, even if the developer's shell exports DATABASE_URL.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_SCHEMA", raising=False)
    path = str(tmp_path / "test_legal.db")
    monkeypatch.setattr(src.db, "DB_PATH", path)
    src.db.init_db(path)
    return path


@pytest.fixture(autouse=True)
def reset_guardrail_state():
    """Rate limiter and call budget are process-global; keep tests independent."""
    from src.guardrails import ikanoon_budget, limiter

    limiter.reset()
    ikanoon_budget.reset()
    yield
    limiter.reset()
    ikanoon_budget.reset()
