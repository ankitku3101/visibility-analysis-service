"""Import pack records into SQLite.

Rules (DESIGN §6):
- every row is validated on its own; bad rows are listed in `rejected_rows` and skipped
- same ID + same content as an earlier import → reused, nothing written
- same ID + different content → whole import rolled back with 409
"""
import sqlite3

from pydantic import BaseModel, ValidationError

from app.analysis.categories import categorize, is_branded
from app.db import content_hash, now, to_json
from app.errors import AppError
from app.ingest.models import CitationIn, PromptIn, ResponseIn, RunIn

MAX_LISTED = 50  # cap on IDs listed in a 409 error


def _reason(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'row'}: {e['msg']}" for e in exc.errors()[:3])


def _check_rows(kind: str, rows: list, model: type[BaseModel], id_field: str,
                run_id: str | None, rejected: list) -> list[tuple[dict, BaseModel]]:
    """Validate rows one by one. Returns (original row, parsed row) for the good ones."""
    good, seen = [], set()
    for row_no, raw in enumerate(rows, start=1):
        shown_id = raw.get(id_field) if isinstance(raw, dict) else None

        def reject(reason: str, detail: str | None = None):
            rejected.append({"file": kind, "row": row_no, "id": shown_id, "reason": reason, "detail": detail})

        if not isinstance(raw, dict):
            reject("not_an_object")
            continue
        try:
            item = model.model_validate(raw)
        except ValidationError as e:
            reject("invalid", _reason(e))
            continue
        if run_id is not None and item.run_id != run_id:
            reject("run_id_mismatch", f"expected {run_id}")
            continue
        key = getattr(item, id_field)
        if key in seen:
            reject("duplicate_in_upload")
            continue
        seen.add(key)
        good.append((raw, item))
    return good


def _drop(kind: str, good: list, keep, reason: str, rejected: list, id_field: str) -> list:
    """Move rows that fail a cross-check from `good` to `rejected`."""
    kept = []
    for raw, item in good:
        problem = keep(item)
        if problem is None:
            kept.append((raw, item))
        else:
            rejected.append({"file": kind, "row": None, "id": getattr(item, id_field), "reason": reason,
                             "detail": problem})
    return kept


def _save(conn: sqlite3.Connection, table: str, pk: str, key: str, raw: dict,
          insert_sql: str, params: tuple, counts: dict, conflicts: list) -> None:
    h = content_hash(raw)
    existing = conn.execute(f"SELECT content_hash FROM {table} WHERE {pk} = ?", (key,)).fetchone()
    if existing is None:
        conn.execute(insert_sql, (*params, h))
        counts["inserted"] += 1
    elif existing["content_hash"] == h:
        counts["reused"] += 1
    else:
        conflicts.append({"file": table, "id": key})


def import_dataset(conn: sqlite3.Connection, records: dict) -> dict:
    try:
        run = RunIn.model_validate(records.get("run"))
    except ValidationError as e:
        raise AppError(422, "bad_run", "The run record is missing or invalid.", _reason(e)) from e
    run_id = run.run_id

    rows = {kind: records.get(kind) or [] for kind in ("prompts", "responses", "citations")}
    counts = {kind: {"received": len(r), "inserted": 0, "reused": 0, "rejected": 0} for kind, r in rows.items()}
    rejected: list[dict] = []

    prompts = _check_rows("prompts", rows["prompts"], PromptIn, "prompt_id", run_id, rejected)
    responses = _check_rows("responses", rows["responses"], ResponseIn, "response_id", run_id, rejected)
    citations = _check_rows("citations", rows["citations"], CitationIn, "citation_id", None, rejected)

    # Cross checks: links must point to rows in this upload or already in the database.
    prompt_ids = {p.prompt_id for _, p in prompts}

    def prompt_known(r: ResponseIn):
        if r.prompt_id in prompt_ids:
            return None
        found = conn.execute("SELECT 1 FROM prompts WHERE prompt_id = ?", (r.prompt_id,)).fetchone()
        return None if found else f"prompt {r.prompt_id} not found"

    responses = _drop("responses", responses, prompt_known, "unknown_prompt", rejected, "response_id")

    # One answer per prompt and engine (the pack checker enforces the same rule).
    pairs_seen: set[tuple[str, str]] = set()

    def one_per_prompt_engine(r: ResponseIn):
        pair = (r.prompt_id, r.engine)
        other = conn.execute("SELECT response_id FROM responses WHERE prompt_id = ? AND engine = ? "
                             "AND response_id != ?", (r.prompt_id, r.engine, r.response_id)).fetchone()
        if pair in pairs_seen or other:
            return f"prompt {r.prompt_id} already has a {r.engine} response"
        pairs_seen.add(pair)
        return None

    responses = _drop("responses", responses, one_per_prompt_engine, "duplicate_prompt_engine", rejected,
                      "response_id")
    response_info = {r.response_id: (r.prompt_id, r.engine) for _, r in responses}

    def response_known(c: CitationIn):
        info = response_info.get(c.response_id)
        if info is None:
            row = conn.execute("SELECT prompt_id, engine FROM responses WHERE response_id = ?",
                               (c.response_id,)).fetchone()
            info = (row["prompt_id"], row["engine"]) if row else None
        if info is None:
            return f"response {c.response_id} not found"
        if info != (c.prompt_id, c.engine):
            return "prompt_id or engine does not match its response"
        return None

    citations = _drop("citations", citations, response_known, "unknown_response", rejected, "citation_id")

    for r in rejected:
        counts[r["file"]]["rejected"] += 1
    if not (prompts or responses or citations):
        raise AppError(422, "no_valid_rows", "No valid rows to import.", rejected[:MAX_LISTED])

    conflicts: list[dict] = []
    with conn:  # one transaction: an exception (e.g. the 409 below) rolls everything back
        # Take the write lock first, so parallel imports run one after another instead of racing.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id FROM datasets WHERE run_id = ?", (run_id,)).fetchone()
        new_dataset = existing is None
        if new_dataset:
            dataset_id = conn.execute("INSERT INTO datasets (run_id, imported_at) VALUES (?, ?)",
                                      (run_id, now())).lastrowid
        else:
            dataset_id = existing["id"]

        for raw, p in prompts:
            _save(conn, "prompts", "prompt_id", p.prompt_id, raw,
                  "INSERT INTO prompts (prompt_id, dataset_id, text, is_branded, category, content_hash) "
                  "VALUES (?, ?, ?, ?, ?, ?)",
                  (p.prompt_id, dataset_id, p.text, int(is_branded(p.text)), categorize(p.text)),
                  counts["prompts"], conflicts)
        for raw, r in responses:
            _save(conn, "responses", "response_id", r.response_id, raw,
                  "INSERT INTO responses (response_id, dataset_id, prompt_id, engine, model_version, answer_text, "
                  "answer_markdown, raw_json, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (r.response_id, dataset_id, r.prompt_id, r.engine, r.model_version, r.answer_text,
                   r.answer_markdown, to_json(raw)),
                  counts["responses"], conflicts)
        for raw, c in citations:
            _save(conn, "citations", "citation_id", c.citation_id, raw,
                  'INSERT INTO citations (citation_id, response_id, engine, "order", citation_type, url, domain, '
                  "title, raw_json, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (c.citation_id, c.response_id, c.engine, c.order, c.citation_type, c.url, c.domain, c.title,
                   to_json(raw)),
                  counts["citations"], conflicts)

        if conflicts:
            raise AppError(409, "duplicate_conflict",
                           f"{len(conflicts)} row(s) already exist with different content. Nothing was imported.",
                           {"total": len(conflicts), "conflicts": conflicts[:MAX_LISTED]})

        conn.execute("UPDATE datasets SET counts = ?, rejected_rows = ? WHERE id = ?",
                     (to_json(counts), to_json(rejected), dataset_id))

    inserted = sum(c["inserted"] for c in counts.values())
    return {
        "dataset_id": dataset_id,
        "run_id": run_id,
        "created": new_dataset or inserted > 0,
        "counts": counts,
        "rejected_rows": rejected,
    }
