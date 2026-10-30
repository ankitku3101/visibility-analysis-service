import sqlite3

from app.config import get_settings


def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok", "llm_mode": "stub"}


def test_startup_creates_all_tables(client):
    conn = sqlite3.connect(get_settings().db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    expected = {
        "datasets", "prompts", "responses", "citations", "analysis_runs", "response_results",
        "llm_calls", "reports", "report_versions", "review_events",
    }
    assert expected <= names


def test_unknown_route_uses_error_format(client):
    res = client.get("/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_unexpected_error_uses_error_format():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.errors import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    res = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert res.status_code == 500
    assert res.json()["error"] == {"code": "internal_error", "message": "Unexpected server error.", "details": None}
