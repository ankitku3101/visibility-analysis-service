"""Analysis runs through the API with a scripted stub model (engineering tests, not model quality)."""
import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm.stub import StubClient
from tests.conftest import ANALYST, REVIEWER
from tests.test_ingest import MINI_PACK, mini_records

REAL_PACK = Path(__file__).parent.parent


def out(**fields) -> str:
    base = {"recommended": False, "recommended_quote": None, "negative": False, "negative_quote": None,
            "competitors": [], "ranked_list": None}
    return "ok:" + json.dumps({**base, **fields})


SCRIPT = {
    "mini-r1": [out(negative=True, negative_quote="Kasparro is a newer tool and is not widely recognized yet.",
                    competitors=["Profound", "ChatGPT"])],
    "mini-r2": [out(recommended=True,
                    recommended_quote="I would recommend trying the Kasparro diagnostic before a larger tool.")],
    "mini-r3": [out(competitors=["Profound", "Otterly.AI"], ranked_list=["Profound", "Kasparro", "Otterly"])],
    "mini-r4": [out(competitors=["Profound", "Otterly", "Peec AI"])],
    # Kasparro only appears in the URL list; the model wrongly says "recommended"
    "mini-r5": [out(recommended=True, recommended_quote="You can use Profound or AthenaHQ to track this.",
                    competitors=["Profound", "AthenaHQ"])],
    "mini-r6": ["malformed", "malformed", "malformed"],
}


def use_stub(client, script):
    client.app.state.client_factory = lambda settings: StubClient(script)


def run_analysis(client, script=SCRIPT, **body) -> dict:
    use_stub(client, script)
    dataset_id = client.post("/datasets", json=mini_records(), headers=ANALYST).json()["dataset_id"]
    res = client.post("/analyses", json={"dataset_id": dataset_id, **body}, headers=ANALYST)
    assert res.status_code == 202, res.text
    return wait(client, res.json()["analysis_id"])


def wait(client, analysis_id, seconds=10) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        run = client.get(f"/analyses/{analysis_id}", headers=ANALYST).json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")


def by_id(run) -> dict:
    return {r["response_id"]: r for r in run["results"]}


def test_every_response_is_accounted_for(client):
    run = run_analysis(client)
    assert run["status"] == "completed"
    assert run["counts"] == {"total": 6, "processed": 6, "succeeded": 5, "failed": 1, "skipped": 0}
    assert run["llm_mode"] == "stub" and run["versions"]["prompt"] == "classify-v1"


def test_labels_evidence_and_competitors(client):
    r = by_id(run_analysis(client))
    assert (r["mini-r1"]["mentioned"], r["mini-r1"]["negative"], r["mini-r1"]["recommended"]) == (True, True, False)
    assert r["mini-r1"]["evidence"]["negative"] == "Kasparro is a newer tool and is not widely recognized yet."
    assert r["mini-r1"]["competitors"] == ["Profound"]  # ChatGPT is not a competitor
    assert r["mini-r2"]["recommended"] is True and r["mini-r2"]["kasparro_cited"] is True
    assert r["mini-r3"]["position"] == 2 and r["mini-r3"]["competitors"] == ["Profound", "Otterly"]
    assert r["mini-r4"]["mentioned"] is False and r["mini-r4"]["position"] is None
    assert r["mini-r4"]["category"] == "discovery" and r["mini-r4"]["is_branded"] is False


def test_url_list_mention_is_not_a_mention_and_labels_are_forced_false(client):
    r5 = by_id(run_analysis(client))["mini-r5"]
    assert (r5["status"], r5["mentioned"], r5["recommended"]) == ("succeeded", False, False)
    assert r5["kasparro_cited"] is True  # the citation is still counted, separately


def test_one_bad_response_fails_alone(client):
    r = by_id(run_analysis(client))
    assert (r["mini-r6"]["status"], r["mini-r6"]["error_code"], r["mini-r6"]["mentioned"]) == \
        ("failed", "malformed_output", None)
    assert all(r[k]["status"] == "succeeded" for k in r if k != "mini-r6")


def test_quote_not_in_answer_fails_after_retries(client):
    script = {"mini-r1": [out(negative=True, negative_quote="Kasparro is a scam and nobody uses it.")] * 3}
    run = run_analysis(client, script)
    assert by_id(run)["mini-r1"]["error_code"] == "evidence_not_found"
    conn = sqlite3.connect(get_settings().db_path)
    attempts = conn.execute("SELECT COUNT(*) FROM llm_calls WHERE response_id = 'mini-r1'").fetchone()[0]
    conn.close()
    assert attempts == 3


def test_unexpected_crash_in_one_response_is_isolated(client):
    run = run_analysis(client, {"mini-r2": ["explode"]})  # unknown stub step raises ValueError
    r = by_id(run)
    assert (r["mini-r2"]["status"], r["mini-r2"]["error_code"]) == ("failed", "internal_error")
    assert run["status"] == "completed" and run["counts"]["succeeded"] == 5


def test_limit(client):
    run = run_analysis(client, limit=2)
    assert run["counts"]["total"] == 2 and len(run["results"]) == 2


def test_call_stats_recorded(client):
    run = run_analysis(client)
    assert run["llm"]["calls"] == 5 + 3 and run["llm"]["cost_usd"] == 0


def test_running_analysis_blocks_a_second_one_and_restart_marks_it_interrupted(client):
    dataset_id = client.post("/datasets", json=mini_records(), headers=ANALYST).json()["dataset_id"]
    conn = sqlite3.connect(get_settings().db_path)
    conn.execute("INSERT INTO analysis_runs (dataset_id, status, llm_mode, prompt_version, category_version, "
                 "scoring_version, started_at) VALUES (?, 'running', 'stub', 'v', 'v', 'v', 'now')", (dataset_id,))
    conn.commit()
    conn.close()
    res = client.post("/analyses", json={"dataset_id": dataset_id}, headers=ANALYST)
    assert res.status_code == 409 and res.json()["error"]["code"] == "analysis_running"

    from app.main import create_app
    with TestClient(create_app()):  # a restart
        pass
    assert client.get("/analyses/1", headers=ANALYST).json()["status"] == "interrupted"


@pytest.mark.parametrize("body, status", [
    ({"dataset_id": 999}, 404),
    ({"dataset_id": 1, "limit": 0}, 422),
    ({"dataset_id": "abc"}, 422),
    ({"dataset_id": 1, "extra": True}, 422),
])
def test_bad_requests(client, body, status):
    client.post("/datasets", json=mini_records(), headers=ANALYST)
    assert client.post("/analyses", json=body, headers=ANALYST).status_code == status


def test_dataset_without_responses_is_422(client):
    body = {"run": {"run_id": "prompts-only"}, "prompts": [{"prompt_id": "p", "run_id": "prompts-only", "text": "q"}]}
    dataset_id = client.post("/datasets", json=body, headers=ANALYST).json()["dataset_id"]
    res = client.post("/analyses", json={"dataset_id": dataset_id}, headers=ANALYST)
    assert res.status_code == 422 and res.json()["error"]["code"] == "dataset_empty"


def test_live_mode_is_400(client, monkeypatch):
    client.post("/datasets", json=mini_records(), headers=ANALYST)
    monkeypatch.setenv("LLM_MODE", "live")
    get_settings.cache_clear()
    res = client.post("/analyses", json={"dataset_id": 1}, headers=ANALYST)
    assert res.status_code == 400 and res.json()["error"]["code"] == "live_not_configured"


def test_roles(client):
    client.post("/datasets", json=mini_records(), headers=ANALYST)
    assert client.post("/analyses", json={"dataset_id": 1}, headers=REVIEWER).status_code == 403
    assert client.get("/analyses/1").status_code == 401
    assert client.get("/analyses/999", headers=REVIEWER).status_code == 404


@pytest.mark.skipif(not (REAL_PACK / "data" / "prompts.jsonl").is_file(), reason="real pack not present")
def test_real_pack_stub_run_covers_all_150(client, monkeypatch):
    monkeypatch.setenv("PACK_DIR", str(REAL_PACK))
    get_settings.cache_clear()
    use_stub(client, {})
    dataset_id = client.post("/datasets", headers=ANALYST).json()["dataset_id"]
    run = wait(client, client.post("/analyses", json={"dataset_id": dataset_id}, headers=ANALYST).json()["analysis_id"],
               seconds=60)
    assert run["counts"] == {"total": 150, "processed": 150, "succeeded": 150, "failed": 0, "skipped": 0}
    assert sum(r["mentioned"] for r in run["results"]) == 72
    assert not any(r["mentioned"] for r in run["results"] if not r["is_branded"])
