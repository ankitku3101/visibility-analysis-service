import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import require_role
from app.config import get_settings
from app.errors import register_error_handlers
from tests.conftest import ANALYST, REVIEWER


@pytest.fixture
def auth_client():
    """A tiny app with one reviewer-only route, so auth is tested on its own."""
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/reviewer-only")
    def reviewer_only(body: dict | None = None, actor: str = Depends(require_role("reviewer"))):
        return {"actor": actor}

    return TestClient(app)


def test_no_token_is_401(auth_client):
    res = auth_client.post("/reviewer-only")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_unknown_token_is_401(auth_client):
    res = auth_client.post("/reviewer-only", headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401


def test_wrong_role_is_403(auth_client):
    res = auth_client.post("/reviewer-only", headers=ANALYST)
    assert res.status_code == 403
    assert res.json()["error"] == {
        "code": "forbidden",
        "message": "This action needs role: reviewer.",
        "details": {"your_role": "analyst"},
    }


def test_right_role_is_200(auth_client):
    res = auth_client.post("/reviewer-only", headers=REVIEWER)
    assert res.status_code == 200
    assert res.json() == {"actor": "reviewer"}


def test_role_in_body_is_ignored(auth_client):
    res = auth_client.post("/reviewer-only", headers=ANALYST, json={"role": "reviewer", "actor": "reviewer"})
    assert res.status_code == 403


def test_non_ascii_token_is_401_not_500(auth_client):
    res = auth_client.post("/reviewer-only", headers={"Authorization": "Bearer café".encode("latin-1")})
    assert res.status_code == 401


def test_same_token_for_both_roles_is_rejected(monkeypatch):
    monkeypatch.setenv("REVIEWER_TOKEN", "same")
    monkeypatch.setenv("ANALYST_TOKEN", "same")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="must be different"):
        get_settings()
