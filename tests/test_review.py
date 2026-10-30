"""Report versions, review rules and export control (stub analysis on the mini pack)."""
import copy
import json
import sqlite3

import pytest

from app.config import get_settings
from tests.conftest import ANALYST, REVIEWER
from tests.test_analysis import SCRIPT, run_analysis

EVIDENCE = {
    "D1": {"response_id": "mini-r4", "quote": "Popular tools include Profound, Otterly and Peec AI."},
    "D2": {"response_id": "mini-r1", "quote": "Kasparro is a newer tool and is not widely recognized yet."},
    "D3": {"response_id": "mini-r2", "quote": "I would recommend trying the Kasparro diagnostic before a larger tool."},
}


def remedy(i: int, diagnostic: str) -> dict:
    return {"id": f"R{i}", "priority": i, "title": f"Remedy {i}", "problem": "Problem text.",
            "diagnostic_ids": [diagnostic], "evidence": [EVIDENCE[diagnostic]], "action": "Investigate X.",
            "expected_benefit": "Benefit.", "effort": "low", "uncertainty": "High; one snapshot.",
            "validation_step": "Re-run the same 50 prompts and compare x/n."}


def filled(draft_content: dict) -> dict:
    """The analyst's edit: explanations, tests, evidence and 3 remedies."""
    diagnostics = copy.deepcopy(draft_content["diagnostics"])
    for d in diagnostics:
        d["explanation"] = "Possible reason."
        d["test_evidence"] = "What would confirm it."
        d["evidence"] = d["evidence"] or [EVIDENCE[d["id"]]]
    return {"diagnostics": diagnostics, "remedies": [remedy(1, "D1"), remedy(2, "D2"), remedy(3, "D3")]}


@pytest.fixture
def report(client) -> dict:
    run = run_analysis(client, SCRIPT)
    res = client.post("/reports", json={"analysis_id": run["analysis_id"]}, headers=ANALYST)
    assert res.status_code == 201, res.text
    return res.json()


def submitted(client, report) -> int:
    rid = report["report_id"]
    assert client.patch(f"/reports/{rid}", json=filled(report["version"]["content"]), headers=ANALYST).status_code == 200
    res = client.post(f"/reports/{rid}/submit", headers=ANALYST)
    assert res.status_code == 200, res.text
    return res.json()["version"]["version_no"]


def decide(client, rid, version, decision="approve", comment="Checked the evidence.", headers=REVIEWER):
    return client.post(f"/reports/{rid}/decision", json={"version": version, "decision": decision,
                                                         "comment": comment}, headers=headers)


def test_draft_has_scores_and_three_diagnostic_drafts(report):
    v = report["version"]
    assert (v["version_no"], v["status"]) == (1, "draft")
    content = v["content"]
    assert content["scores"]["unbranded"]["all"]["total"] == 3 and content["remedies"] == []
    d1, d2, d3 = content["diagnostics"]
    assert "0/2 succeeded unbranded answers" in d1["pattern"] and "Profound (2)" in d1["pattern"]
    assert d1["evidence"] and all(e["response_id"] in {"mini-r4", "mini-r5"} for e in d1["evidence"])
    assert "1/3 describe it negatively" in d2["pattern"]
    assert {"response_id": "mini-r1", "quote": EVIDENCE["D2"]["quote"]} in d2["evidence"]
    assert "ChatGPT 100.0" in d3["pattern"] and "gap 70.0" in d3["pattern"]
    assert d1["explanation"] == "" and report["events"][0]["action"] == "create"


def test_draft_evidence_falls_back_when_nothing_is_labelled(client):
    run = run_analysis(client, {})  # default stub: nothing recommended/negative, no competitors
    content = client.post("/reports", json={"analysis_id": run["analysis_id"]}, headers=ANALYST).json()["version"]["content"]
    d1, d2, _ = content["diagnostics"]
    assert d1["evidence"] and {e["response_id"] for e in d1["evidence"]} <= {"mini-r4", "mini-r5", "mini-r6"}
    assert d2["evidence"] and all("Kasparro" in e["quote"] for e in d2["evidence"])


def test_full_review_flow(client, report):
    rid = report["report_id"]
    v1 = submitted(client, report)

    assert decide(client, rid, v1, headers=ANALYST).status_code == 403              # wrong role
    assert client.patch(f"/reports/{rid}", json={"notes": "x"}, headers=REVIEWER).status_code == 403
    assert decide(client, rid, v1, headers={}).status_code == 401                    # no token

    assert decide(client, rid, v1, "reject", "Remedy 2 is too vague.").json()["version"]["status"] == "rejected"
    blocked = client.get(f"/reports/{rid}/export", headers=ANALYST)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "not_approved"

    # edit after rejection → version 2 draft; version 1 stays rejected
    res = client.patch(f"/reports/{rid}", json={"notes": "Clarified remedy 2."}, headers=ANALYST).json()
    assert (res["version"]["version_no"], res["version"]["status"]) == (2, "draft")
    assert [v["status"] for v in res["versions"]] == ["rejected", "draft"]
    assert client.post(f"/reports/{rid}/submit", headers=ANALYST).status_code == 200
    assert decide(client, rid, 2).json()["version"]["status"] == "approved"

    export = client.get(f"/reports/{rid}/export", headers=REVIEWER).json()
    assert (export["version"], export["is_latest"], export["approval"]["actor"]) == (2, True, "reviewer")
    assert export["content"]["notes"] == "Clarified remedy 2." and export["llm_mode"] == "stub"

    # edit after approval → version 3 draft, needs a new review
    client.patch(f"/reports/{rid}", json={"notes": "One more change."}, headers=ANALYST)
    latest = client.get(f"/reports/{rid}/export", headers=ANALYST)
    assert latest.status_code == 409 and latest.json()["error"]["details"]["status"] == "draft"
    old = client.get(f"/reports/{rid}/export?version=2", headers=ANALYST).json()
    assert (old["version"], old["is_latest"]) == (2, False) and "Latest is version 3" in old["notice"]
    assert old["content"]["notes"] == "Clarified remedy 2."                         # old version unchanged

    events = client.get(f"/reports/{rid}", headers=ANALYST).json()["events"]
    assert [e["action"] for e in events] == ["create", "edit", "submit", "reject", "edit", "submit", "approve",
                                             "export", "edit", "export"]
    assert events[3] | {"at": None} == {"version_no": 1, "actor": "reviewer", "action": "reject",
                                        "comment": "Remedy 2 is too vague.", "at": None}


def test_decision_rules(client, report):
    rid = report["report_id"]
    assert decide(client, rid, 1).json()["error"]["code"] == "not_submitted"         # still a draft
    v1 = submitted(client, report)
    assert decide(client, rid, v1, comment="   ").status_code == 422                  # blank comment
    assert client.post(f"/reports/{rid}/decision", json={"decision": "approve", "comment": "ok"},
                       headers=REVIEWER).status_code == 422                            # version missing
    # editing a submitted (undecided) version makes v2; deciding the old v1 is refused
    client.patch(f"/reports/{rid}", json={"notes": "late fix"}, headers=ANALYST)
    stale = decide(client, rid, v1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "not_latest_version"
    assert client.post(f"/reports/{rid}/submit", headers=ANALYST).status_code == 200
    assert decide(client, rid, 2).status_code == 200
    assert decide(client, rid, 2).json()["error"]["code"] == "not_submitted"         # no double decision
    assert client.post(f"/reports/{rid}/submit", headers=ANALYST).json()["error"]["code"] == "not_a_draft"


def test_role_sent_in_body_is_not_authorisation(client, report):
    v1 = submitted(client, report)
    res = client.post(f"/reports/{report['report_id']}/decision", headers=ANALYST,
                      json={"version": v1, "decision": "approve", "comment": "ok", "actor": "reviewer"})
    assert res.status_code == 403


@pytest.mark.parametrize("change, code", [
    (lambda c: c["diagnostics"][0]["evidence"].append({"response_id": "mini-r4", "quote": "Kasparro is the best tool."}),
     "quote_not_found"),
    (lambda c: c["diagnostics"][0]["evidence"].append({"response_id": "made-up-id", "quote": "anything at all"}),
     "unknown_response"),
    (lambda c: c["remedies"][0]["diagnostic_ids"].append("D9"), "unknown_diagnostic"),
    (lambda c: c["remedies"][1].update(priority=1), "duplicate_priority"),
    (lambda c: c["remedies"][1].update(id="R1"), "duplicate_id"),
])
def test_unsupported_or_wrong_evidence_is_rejected(client, report, change, code):
    body = filled(report["version"]["content"])
    change(body)
    res = client.patch(f"/reports/{report['report_id']}", json=body, headers=ANALYST)
    assert res.status_code == 422
    assert code in {p["code"] for p in res.json()["error"]["details"]}


def test_evidence_from_a_response_outside_the_analysis_is_rejected(client):
    run = run_analysis(client, SCRIPT, limit=3)  # only mini:001 responses analysed
    rid = client.post("/reports", json={"analysis_id": run["analysis_id"]}, headers=ANALYST).json()["report_id"]
    res = client.patch(f"/reports/{rid}", headers=ANALYST, json={"diagnostics": [
        {"id": "D1", "title": "t", "evidence": [EVIDENCE["D1"]]}]})  # mini-r4 exists but was not analysed
    assert res.json()["error"]["details"][0]["code"] == "unknown_response"


@pytest.mark.parametrize("body", [{"scores": {}}, {"notes": "x", "actor": "reviewer"}, {}])
def test_bad_patch_bodies(client, report, body):
    assert client.patch(f"/reports/{report['report_id']}", json=body, headers=ANALYST).status_code == 422


def test_incomplete_report_cannot_be_submitted(client, report):
    rid = report["report_id"]
    body = filled(report["version"]["content"])
    body["remedies"] = body["remedies"][:2]
    body["diagnostics"][0]["explanation"] = ""
    client.patch(f"/reports/{rid}", json=body, headers=ANALYST)
    res = client.post(f"/reports/{rid}/submit", headers=ANALYST)
    assert res.status_code == 422
    codes = {(p["path"], p["code"]) for p in res.json()["error"]["details"]}
    assert ("remedies", "wrong_count") in codes and ("diagnostics[0].explanation", "missing_field") in codes


def test_changed_content_in_database_blocks_approval_and_export(client, report):
    rid = report["report_id"]
    v1 = submitted(client, report)

    def tamper():
        conn = sqlite3.connect(get_settings().db_path)
        row = conn.execute("SELECT content FROM report_versions WHERE report_id = ?", (rid,)).fetchone()
        content = json.loads(row[0])
        content["notes"] = "changed behind the API"
        conn.execute("UPDATE report_versions SET content = ? WHERE report_id = ?", (json.dumps(content), rid))
        conn.commit()
        conn.close()

    tamper()
    assert decide(client, rid, v1).json()["error"]["code"] == "hash_mismatch"


def test_changed_content_after_approval_blocks_export(client, report):
    rid = report["report_id"]
    decide(client, rid, submitted(client, report))
    assert client.get(f"/reports/{rid}/export", headers=ANALYST).status_code == 200
    conn = sqlite3.connect(get_settings().db_path)
    conn.execute("UPDATE report_versions SET content = replace(content, 'Possible reason.', 'Edited in DB.') "
                 "WHERE report_id = ?", (rid,))
    conn.commit()
    conn.close()
    res = client.get(f"/reports/{rid}/export", headers=ANALYST)
    assert res.status_code == 409 and res.json()["error"]["code"] == "hash_mismatch"


def test_two_reviewers_deciding_at_once_get_one_decision(client, report):
    from concurrent.futures import ThreadPoolExecutor
    rid = report["report_id"]
    v1 = submitted(client, report)
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda d: decide(client, rid, v1, d).status_code, ["approve", "reject"] * 2))
    assert sorted(codes) == [200, 409, 409, 409]
    decisions = [e for e in client.get(f"/reports/{rid}", headers=ANALYST).json()["events"]
                 if e["action"] in ("approve", "reject")]
    assert len(decisions) == 1


def test_report_needs_completed_analysis_and_analyst(client):
    assert client.post("/reports", json={"analysis_id": 99}, headers=ANALYST).status_code == 404
    run = run_analysis(client, SCRIPT)
    assert client.post("/reports", json={"analysis_id": run["analysis_id"]}, headers=REVIEWER).status_code == 403
    conn = sqlite3.connect(get_settings().db_path)
    conn.execute("UPDATE analysis_runs SET status = 'interrupted'")
    conn.commit()
    conn.close()
    res = client.post("/reports", json={"analysis_id": run["analysis_id"]}, headers=ANALYST)
    assert res.status_code == 409 and res.json()["error"]["code"] == "analysis_not_completed"


def test_unknown_report_and_version(client, report):
    assert client.get("/reports/99", headers=ANALYST).status_code == 404
    assert client.get(f"/reports/{report['report_id']}?version=7", headers=ANALYST).status_code == 404
    assert client.get(f"/reports/{report['report_id']}/export?version=0", headers=ANALYST).status_code == 422
