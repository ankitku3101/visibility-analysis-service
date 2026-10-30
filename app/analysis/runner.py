"""Runs one analysis in a background thread. One result row per response, saved as soon as it is ready."""
import json
import logging
import threading

from app.analysis.service import analyse_response
from app.config import Settings
from app.db import connect, now, to_json
from app.llm.client import Budget, LLMClient
from app.llm.prompts import PROMPT_VERSION

log = logging.getLogger("app.runner")


def start_run(run_id: int, client: LLMClient, settings: Settings) -> threading.Thread:
    thread = threading.Thread(target=execute_run, args=(run_id, client, settings), daemon=True,
                              name=f"analysis-{run_id}")
    thread.start()
    return thread


def _save_result(conn, run_id: int, result: dict, calls: list[dict], counts: dict, client: LLMClient) -> None:
    with conn:
        for c in calls:
            conn.execute(
                "INSERT INTO llm_calls (analysis_id, response_id, attempt, mode, model, prompt_version, status, "
                "latency_ms, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, result["response_id"], c["attempt"], client.mode, client.model, PROMPT_VERSION,
                 c["status"], c["latency_ms"],
                 f"{c['error_code']}: {c['error_detail']}"[:500] if c.get("error_detail") else c["error_code"]))

        def flag(v):
            return None if v is None else int(v)

        conn.execute(
            "INSERT INTO response_results (analysis_id, response_id, status, error_code, skip_reason, mentioned, "
            "recommended, negative, evidence, competitors, ranked_list, position, kasparro_cited) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, result["response_id"], result["status"], result["error_code"], result["skip_reason"],
             flag(result["mentioned"]), flag(result["recommended"]), flag(result["negative"]),
             to_json(result["evidence"]), to_json(result["competitors"]),
             to_json(result["ranked_list"]) if result["ranked_list"] is not None else None,
             result["position"], flag(result["kasparro_cited"])))
        conn.execute(
            "UPDATE analysis_runs SET counts = ?, llm_calls = llm_calls + ?, llm_seconds = llm_seconds + ? "
            "WHERE id = ?",
            (to_json(counts), len(calls), sum(c["latency_ms"] for c in calls) / 1000, run_id))


def execute_run(run_id: int, client: LLMClient, settings: Settings) -> None:
    conn = connect(settings.db_path)
    try:
        run = conn.execute("SELECT dataset_id, \"limit\" FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        rows = conn.execute(
            "SELECT r.response_id, r.answer_text, r.raw_json, p.text AS question FROM responses r "
            "JOIN prompts p ON p.prompt_id = r.prompt_id WHERE r.dataset_id = ? "
            "ORDER BY r.prompt_id, r.engine LIMIT ?",
            (run["dataset_id"], run["limit"] or -1)).fetchall()
        counts = {"total": len(rows), "processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
        with conn:
            conn.execute("UPDATE analysis_runs SET counts = ? WHERE id = ?", (to_json(counts), run_id))
        budget = Budget(limit=settings.llm_max_calls)

        for row in rows:
            calls: list[dict] = []
            try:
                citations = [dict(c) for c in conn.execute(
                    "SELECT domain, url FROM citations WHERE response_id = ?", (row["response_id"],))]
                response = {"response_id": row["response_id"], "answer_text": row["answer_text"],
                            "capture_status": json.loads(row["raw_json"]).get("capture_status")}
                result = analyse_response(response, row["question"], citations, client, settings, budget,
                                          log=lambda **kw: calls.append(kw))
            except Exception:
                # A bug or bad record affects only this response; the run continues.
                log.exception("Analysis of %s failed", row["response_id"])
                result = {"response_id": row["response_id"], "status": "failed", "error_code": "internal_error",
                          "skip_reason": None, "mentioned": None, "recommended": None, "negative": None,
                          "evidence": {}, "competitors": [], "ranked_list": None, "position": None,
                          "kasparro_cited": None}
            counts["processed"] += 1
            counts[result["status"]] += 1
            _save_result(conn, run_id, result, calls, counts, client)

        with conn:
            conn.execute("UPDATE analysis_runs SET status = 'completed', finished_at = ? WHERE id = ?", (now(), run_id))
    except Exception:
        log.exception("Analysis run %s crashed", run_id)
        with conn:
            conn.execute("UPDATE analysis_runs SET status = 'failed', finished_at = ? WHERE id = ?", (now(), run_id))
    finally:
        conn.close()


def mark_interrupted(conn) -> int:
    """At startup, a run still marked running was cut off by a restart (one server process assumed)."""
    with conn:
        return conn.execute("UPDATE analysis_runs SET status = 'interrupted', finished_at = ? "
                            "WHERE status = 'running'", (now(),)).rowcount
