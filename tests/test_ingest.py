import copy
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.config import get_settings
from app.ingest.loader import load_pack
from tests.conftest import ANALYST, REVIEWER

MINI_PACK = Path(__file__).parent / "fixtures" / "mini_pack"
REAL_PACK = Path(__file__).parent.parent


def mini_records() -> dict:
    return copy.deepcopy(load_pack(str(MINI_PACK)))


def table_counts() -> dict:
    conn = sqlite3.connect(get_settings().db_path)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("prompts", "responses", "citations")}
    conn.close()
    return out


def use_pack_dir(monkeypatch, path):
    monkeypatch.setenv("PACK_DIR", str(path))
    get_settings.cache_clear()


def test_import_from_body(client):
    res = client.post("/datasets", json=mini_records(), headers=ANALYST)
    assert res.status_code == 201
    body = res.json()
    assert body["run_id"] == "mini-run-1"
    assert body["rejected_rows"] == []
    assert body["counts"]["responses"] == {"received": 6, "inserted": 6, "reused": 0, "rejected": 0}
    assert table_counts() == {"prompts": 2, "responses": 6, "citations": 7}


def test_import_from_pack_dir(client, monkeypatch):
    use_pack_dir(monkeypatch, MINI_PACK)
    res = client.post("/datasets", headers=ANALYST)
    assert res.status_code == 201
    assert table_counts() == {"prompts": 2, "responses": 6, "citations": 7}


@pytest.mark.skipif(not (REAL_PACK / "data" / "prompts.jsonl").is_file(), reason="real pack not present")
def test_import_real_pack(client, monkeypatch):
    use_pack_dir(monkeypatch, REAL_PACK)
    res = client.post("/datasets", headers=ANALYST)
    assert res.status_code == 201
    assert res.json()["rejected_rows"] == []
    assert table_counts() == {"prompts": 50, "responses": 150, "citations": 2439}


def test_reimport_reuses_and_adds_nothing(client):
    first = client.post("/datasets", json=mini_records(), headers=ANALYST).json()
    res = client.post("/datasets", json=mini_records(), headers=ANALYST)
    assert res.status_code == 200
    body = res.json()
    assert body["dataset_id"] == first["dataset_id"]
    assert body["counts"]["citations"] == {"received": 7, "inserted": 0, "reused": 7, "rejected": 0}
    assert table_counts() == {"prompts": 2, "responses": 6, "citations": 7}


def test_changed_content_same_id_is_409_and_nothing_written(client):
    client.post("/datasets", json=mini_records(), headers=ANALYST)
    records = mini_records()
    records["responses"][0]["answer_text"] = "changed text"
    records["prompts"].append({"prompt_id": "mini:003", "run_id": "mini-run-1", "text": "a new question"})
    res = client.post("/datasets", json=records, headers=ANALYST)
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "duplicate_conflict"
    assert err["details"]["conflicts"] == [{"file": "responses", "id": "mini-r1"}]
    # rolled back: the new prompt was not saved and the old text is unchanged
    assert table_counts()["prompts"] == 2
    conn = sqlite3.connect(get_settings().db_path)
    assert conn.execute("SELECT answer_text FROM responses WHERE response_id = 'mini-r1'").fetchone()[0] != "changed text"
    conn.close()


def test_bad_row_is_listed_and_others_are_saved(client):
    records = mini_records()
    del records["responses"][0]["answer_text"]
    res = client.post("/datasets", json=records, headers=ANALYST)
    assert res.status_code == 201
    rejected = res.json()["rejected_rows"]
    assert {"file": "responses", "id": "mini-r1", "reason": "invalid"}.items() <= rejected[0].items()
    assert "answer_text" in rejected[0]["detail"]
    # its citation now points to a missing response, so it is skipped too
    assert {r["id"]: r["reason"] for r in rejected[1:]} == {"MINI-C1": "unknown_response"}
    assert table_counts() == {"prompts": 2, "responses": 5, "citations": 6}


@pytest.mark.parametrize("change, reason", [
    (lambda r: r["responses"].__setitem__(1, "not an object"), "not_an_object"),
    (lambda r: r["responses"][1].update(run_id="other-run"), "run_id_mismatch"),
    (lambda r: r["responses"][1].update(prompt_id="missing"), "unknown_prompt"),
    (lambda r: r["responses"].append(dict(r["responses"][1])), "duplicate_in_upload"),
    (lambda r: r["responses"][1].update(engine="perplexity"), "invalid"),
    (lambda r: r["responses"][1].update(capture_status="failed"), "invalid"),
    (lambda r: r["citations"][1].update(order="1"), "invalid"),
    (lambda r: r["citations"][1].update(engine="gemini"), "unknown_response"),
    (lambda r: r["responses"].append({**r["responses"][1], "response_id": "new-id"}), "duplicate_prompt_engine"),
])
def test_row_level_rejections(client, change, reason):
    records = mini_records()
    change(records)
    res = client.post("/datasets", json=records, headers=ANALYST)
    assert res.status_code == 201
    assert reason in {r["reason"] for r in res.json()["rejected_rows"]}


def test_null_values_stay_null(client):
    client.post("/datasets", json=mini_records(), headers=ANALYST)
    conn = sqlite3.connect(get_settings().db_path)
    row = conn.execute("SELECT model_version, raw_json FROM responses WHERE response_id = 'mini-r1'").fetchone()
    conn.close()
    assert row[0] is None
    raw = json.loads(row[1])
    assert raw["settings"]["force_web_search"] is None
    assert raw["engine_name"] == "Google AI Mode"  # extra fields kept


def test_missing_file_is_422(client, monkeypatch, tmp_path):
    shutil.copytree(MINI_PACK, tmp_path / "pack")
    (tmp_path / "pack" / "data" / "citations.jsonl").unlink()
    use_pack_dir(monkeypatch, tmp_path / "pack")
    res = client.post("/datasets", headers=ANALYST)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "bad_file"


def test_broken_json_line_is_422_with_line_number(client, monkeypatch, tmp_path):
    shutil.copytree(MINI_PACK, tmp_path / "pack")
    path = tmp_path / "pack" / "data" / "prompts.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    use_pack_dir(monkeypatch, tmp_path / "pack")
    res = client.post("/datasets", headers=ANALYST)
    assert res.status_code == 422
    assert res.json()["error"]["details"] == {"file": "data/prompts.jsonl", "line": 3}
    assert table_counts() == {"prompts": 0, "responses": 0, "citations": 0}


def test_file_with_bom_is_accepted(client, monkeypatch, tmp_path):
    shutil.copytree(MINI_PACK, tmp_path / "pack")
    path = tmp_path / "pack" / "data" / "prompts.jsonl"
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    use_pack_dir(monkeypatch, tmp_path / "pack")
    assert client.post("/datasets", headers=ANALYST).status_code == 201


def test_parallel_imports_do_not_crash(client):
    records = mini_records()
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: client.post("/datasets", json=records, headers=ANALYST).status_code, range(4)))
    assert sorted(codes) == [200, 200, 200, 201]
    assert table_counts() == {"prompts": 2, "responses": 6, "citations": 7}


def test_missing_run_is_422(client):
    records = mini_records()
    del records["run"]
    assert client.post("/datasets", json=records, headers=ANALYST).status_code == 422


def test_no_valid_rows_is_422(client):
    res = client.post("/datasets", json={"run": {"run_id": "x"}, "prompts": [{"bad": 1}]}, headers=ANALYST)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "no_valid_rows"


def test_reviewer_cannot_import(client):
    assert client.post("/datasets", json=mini_records(), headers=REVIEWER).status_code == 403


def test_no_token_is_401_even_with_bad_body(client):
    assert client.post("/datasets", json={"nonsense": True}).status_code == 401
