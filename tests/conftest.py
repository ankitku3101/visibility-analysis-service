import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

ANALYST_TOKEN = "test-analyst-token"
REVIEWER_TOKEN = "test-reviewer-token"
ANALYST = {"Authorization": f"Bearer {ANALYST_TOKEN}"}
REVIEWER = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}


@pytest.fixture(autouse=True)
def test_env(tmp_path, monkeypatch):
    """Every setting is set here, so a developer's local .env never leaks into tests."""
    env = {
        "DB_PATH": str(tmp_path / "test.db"),
        "PACK_DIR": ".",
        "LLM_MODE": "stub",
        "REPLAY_DIR": str(tmp_path / "replay"),
        "ANALYST_TOKEN": ANALYST_TOKEN,
        "REVIEWER_TOKEN": REVIEWER_TOKEN,
        "OLLAMA_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:7b",
        "LLM_TIMEOUT_S": "5",
        "LLM_MAX_RETRIES": "2",
        "LLM_MAX_CALLS": "450",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
