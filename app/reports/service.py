"""Report versions and the review state machine.

draft --submit--> submitted --approve--> approved
                            --reject---> rejected
PATCH on the latest draft edits it in place. PATCH when the latest is submitted/approved/rejected copies it
into a new draft (version + 1), which needs its own review. Content of a non-draft version never changes.
"""
import json
import sqlite3

from pydantic import ValidationError

from app.db import content_hash, now, to_json
from app.errors import AppError
from app.reports.draft import build_draft
from app.reports.models import DecisionBody, PatchBody, ReportContent
from app.reports.validate import validate_content


def _event(conn, report_id: int, version_no: int, actor: str, action: str, comment: str | None = None):
    conn.execute("INSERT INTO review_events (report_id, version_no, actor, action, comment, at) "
                 "VALUES (?, ?, ?, ?, ?, ?)", (report_id, version_no, actor, action, comment, now()))


def _report(conn, report_id: int):
    report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not report:
        raise AppError(404, "report_not_found", f"Report {report_id} does not exist.")
    return report


def _version(conn, report_id: int, version_no: int | None = None):
    if version_no is None:
        row = conn.execute("SELECT * FROM report_versions WHERE report_id = ? ORDER BY version_no DESC LIMIT 1",
                           (report_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM report_versions WHERE report_id = ? AND version_no = ?",
                           (report_id, version_no)).fetchone()
    if not row:
        raise AppError(404, "version_not_found", f"Report {report_id} has no version {version_no}.")
    return row


def _check_hash(row) -> dict:
    content = json.loads(row["content"])
    if content_hash(content) != row["content_hash"]:
        raise AppError(409, "hash_mismatch", f"Version {row['version_no']} was changed after it was saved.",
                       {"version": row["version_no"]})
    return content


def create_report(conn: sqlite3.Connection, analysis_id: int, actor: str) -> int:
    run = conn.execute("SELECT status FROM analysis_runs WHERE id = ?", (analysis_id,)).fetchone()
    if not run:
        raise AppError(404, "analysis_not_found", f"Analysis {analysis_id} does not exist.")
    if run["status"] != "completed":
        raise AppError(409, "analysis_not_completed", f"Analysis {analysis_id} is {run['status']}.")
    content = ReportContent.model_validate(build_draft(conn, analysis_id))
    validate_content(conn, analysis_id, content, complete=False)
    data = content.model_dump()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        report_id = conn.execute("INSERT INTO reports (analysis_id, created_by, created_at) VALUES (?, ?, ?)",
                                 (analysis_id, actor, now())).lastrowid
        conn.execute("INSERT INTO report_versions (report_id, version_no, status, content, content_hash, created_by, "
                     "created_at) VALUES (?, 1, 'draft', ?, ?, ?, ?)",
                     (report_id, to_json(data), content_hash(data), actor, now()))
        _event(conn, report_id, 1, actor, "create")
    return report_id


def get_report(conn: sqlite3.Connection, report_id: int, version_no: int | None = None) -> dict:
    report = _report(conn, report_id)
    row = _version(conn, report_id, version_no)
    latest = _version(conn, report_id)
    versions = conn.execute("SELECT version_no, status, created_by, created_at FROM report_versions "
                            "WHERE report_id = ? ORDER BY version_no", (report_id,)).fetchall()
    events = conn.execute("SELECT version_no, actor, action, comment, at FROM review_events WHERE report_id = ? "
                          "ORDER BY id", (report_id,)).fetchall()
    return {
        "report_id": report_id, "analysis_id": report["analysis_id"], "latest_version": latest["version_no"],
        "version": {"version_no": row["version_no"], "status": row["status"], "content_hash": row["content_hash"],
                    "created_by": row["created_by"], "created_at": row["created_at"],
                    "content": json.loads(row["content"])},
        "versions": [dict(v) for v in versions],
        "events": [dict(e) for e in events],
    }


def patch_report(conn: sqlite3.Connection, report_id: int, body: PatchBody, actor: str) -> int:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(422, "empty_patch", "Send at least one of: diagnostics, remedies, notes.")
    report = _report(conn, report_id)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = _version(conn, report_id)
        try:
            content = ReportContent.model_validate(json.loads(latest["content"]) | changes)
        except ValidationError as e:  # e.g. {"notes": null}: the request is wrong, not the server
            details = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]
            raise AppError(422, "validation_error", "The edited report is not valid.", details) from None
        validate_content(conn, report["analysis_id"], content, complete=False)
        data = content.model_dump()
        if latest["status"] == "draft":
            version_no = latest["version_no"]
            conn.execute("UPDATE report_versions SET content = ?, content_hash = ? WHERE id = ?",
                         (to_json(data), content_hash(data), latest["id"]))
            _event(conn, report_id, version_no, actor, "edit")
        else:
            version_no = latest["version_no"] + 1
            conn.execute("INSERT INTO report_versions (report_id, version_no, status, content, content_hash, "
                         "created_by, created_at) VALUES (?, ?, 'draft', ?, ?, ?, ?)",
                         (report_id, version_no, to_json(data), content_hash(data), actor, now()))
            _event(conn, report_id, version_no, actor, "edit",
                   f"New draft from version {latest['version_no']} ({latest['status']}); needs a new review.")
    return version_no


def submit_report(conn: sqlite3.Connection, report_id: int, actor: str) -> int:
    report = _report(conn, report_id)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = _version(conn, report_id)
        if latest["status"] != "draft":
            raise AppError(409, "not_a_draft", f"Version {latest['version_no']} is {latest['status']}; edit it to "
                           "create a new draft first.", {"version": latest["version_no"], "status": latest["status"]})
        content = ReportContent.model_validate(_check_hash(latest))
        validate_content(conn, report["analysis_id"], content, complete=True)
        conn.execute("UPDATE report_versions SET status = 'submitted' WHERE id = ?", (latest["id"],))
        _event(conn, report_id, latest["version_no"], actor, "submit")
    return latest["version_no"]


def decide(conn: sqlite3.Connection, report_id: int, body: DecisionBody, actor: str) -> str:
    _report(conn, report_id)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = _version(conn, report_id)
        if body.version != latest["version_no"]:
            raise AppError(409, "not_latest_version", f"Version {body.version} is not the latest "
                           f"(latest is {latest['version_no']}).", {"latest_version": latest["version_no"]})
        if latest["status"] != "submitted":
            raise AppError(409, "not_submitted", f"Version {body.version} is {latest['status']}, not submitted.",
                           {"version": body.version, "status": latest["status"]})
        _check_hash(latest)
        status = "approved" if body.decision == "approve" else "rejected"
        conn.execute("UPDATE report_versions SET status = ? WHERE id = ?", (status, latest["id"]))
        _event(conn, report_id, body.version, actor, body.decision, body.comment)
    return status


def export_report(conn: sqlite3.Connection, report_id: int, version_no: int | None, actor: str) -> dict:
    report = _report(conn, report_id)
    row = _version(conn, report_id, version_no)
    latest = _version(conn, report_id)
    if row["status"] != "approved":
        raise AppError(409, "not_approved", f"Version {row['version_no']} is {row['status']}; only approved "
                       "versions can be exported.",
                       {"version": row["version_no"], "status": row["status"], "latest_version": latest["version_no"]})
    content = _check_hash(row)
    approval = conn.execute("SELECT actor, comment, at FROM review_events WHERE report_id = ? AND version_no = ? "
                            "AND action = 'approve' ORDER BY id DESC LIMIT 1", (report_id, row["version_no"])).fetchone()
    run = conn.execute("SELECT llm_mode, model, prompt_version, category_version, scoring_version FROM analysis_runs "
                       "WHERE id = ?", (report["analysis_id"],)).fetchone()
    with conn:
        _event(conn, report_id, row["version_no"], actor, "export")
    is_latest = row["version_no"] == latest["version_no"]
    return {
        "report_id": report_id, "analysis_id": report["analysis_id"],
        "version": row["version_no"], "is_latest": is_latest,
        "notice": None if is_latest else (f"Older approved version. Latest is version {latest['version_no']} "
                                          f"({latest['status']})."),
        "status": "approved", "content_hash": row["content_hash"],
        "approval": dict(approval) if approval else None,
        "llm_mode": run["llm_mode"], "model": run["model"],
        "versions": {"prompt": run["prompt_version"], "category": run["category_version"],
                     "scoring": run["scoring_version"]},
        "exported_by": actor, "exported_at": now(),
        "content": content,
    }
