"""Group stats and the full scores block for one analysis run. Every number carries its count and total."""
import json
import sqlite3
from collections import defaultdict

from app.errors import AppError
from app.scoring.citations import citation_stats
from app.scoring.score import METHOD, response_parts, response_points

ENGINES = ("aimode", "chatgpt", "gemini")
LOW_COVERAGE = 0.8


def ratio(x: int, n: int) -> dict:
    return {"x": x, "n": n, "rate": round(x / n, 3) if n else None}


def group_stats(results: list[dict]) -> dict:
    total = len(results)
    succeeded = [r for r in results if r["status"] == "succeeded"]
    failed = sum(r["status"] == "failed" for r in results)
    skipped = sum(r["status"] == "skipped" for r in results)
    n = len(succeeded)

    points = [response_points(r)["total"] for r in succeeded]
    parts = [response_parts(r) for r in succeeded]
    mentioned = [r for r in succeeded if r["mentioned"]]
    tried = n + failed  # skipped responses are not part of the range

    return {
        "total": total, "succeeded": n, "failed": failed, "skipped": skipped,
        "coverage": ratio(n, total),
        "low_coverage": total > 0 and n / total < LOW_COVERAGE,
        "score": round(sum(points) / n, 1) if n else None,
        "score_range": [round(sum(points) / tried, 1), round((sum(points) + 100 * failed) / tried, 1)] if tried else None,
        "parts": {name: ratio(sum(p[name] for p in parts), n) for name in ("mentioned", "recommended", "not_negative", "cited")},
        "negative": ratio(sum(bool(r["negative"]) for r in succeeded), n),
        "when_mentioned": {
            "recommended": ratio(sum(bool(r["recommended"]) for r in mentioned), len(mentioned)),
            "negative": ratio(sum(bool(r["negative"]) for r in mentioned), len(mentioned)),
        },
    }


def _by(results: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for r in results:
        groups[r[key]].append(r)
    return {k: group_stats(v) for k, v in sorted(groups.items())}


def _same_prompt_comparison(results: list[dict]) -> dict:
    """Engines compared only on prompts where all three engines succeeded (same questions, fair comparison)."""
    by_prompt = defaultdict(dict)
    for r in results:
        by_prompt[r["prompt_id"]][r["engine"]] = r
    shared = [p for p, engines in by_prompt.items()
              if all(e in engines and engines[e]["status"] == "succeeded" for e in ENGINES)]
    per_engine = {e: [response_points(by_prompt[p][e])["total"] for p in shared] for e in ENGINES}
    return {
        "prompts": len(shared),
        "by_engine": {e: round(sum(v) / len(v), 1) if v else None for e, v in per_engine.items()},
        "prompt_ids": sorted(shared),
    }


def _competitors(results: list[dict]) -> list[dict]:
    counts = defaultdict(lambda: {"branded": 0, "unbranded": 0})
    for r in results:
        if r["status"] != "succeeded":
            continue
        for name in set(r["competitors"]):
            counts[name]["branded" if r["is_branded"] else "unbranded"] += 1
    rows = [{"name": k, **v, "total": v["branded"] + v["unbranded"]} for k, v in counts.items()]
    return sorted(rows, key=lambda x: (-x["total"], x["name"]))


def _per_prompt(results: list[dict], texts: dict) -> list[dict]:
    rows = {}
    for r in results:
        row = rows.setdefault(r["prompt_id"], {
            "prompt_id": r["prompt_id"], "text": texts[r["prompt_id"]], "category": r["category"],
            "is_branded": r["is_branded"], "engines": {e: None for e in ENGINES}})
        pts = response_points(r)
        row["engines"][r["engine"]] = {
            "response_id": r["response_id"], "status": r["status"], "error_code": r["error_code"],
            "mentioned": r["mentioned"], "recommended": r["recommended"], "negative": r["negative"],
            "position": r["position"], "cited": r["kasparro_cited"], "points": pts["total"] if pts else None,
        }
    return [rows[k] for k in sorted(rows)]


def build_scores(conn: sqlite3.Connection, analysis_id: int) -> dict:
    run = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (analysis_id,)).fetchone()
    if not run:
        raise AppError(404, "analysis_not_found", f"Analysis {analysis_id} does not exist.")
    rows = conn.execute(
        "SELECT rr.*, r.prompt_id, r.engine, p.category, p.is_branded, p.text FROM response_results rr "
        "JOIN responses r ON r.response_id = rr.response_id JOIN prompts p ON p.prompt_id = r.prompt_id "
        "WHERE rr.analysis_id = ?", (analysis_id,)).fetchall()
    def flag(v):  # failed/skipped rows keep None: unknown, not "false"
        return None if v is None else v == 1

    results = [{
        "response_id": r["response_id"], "prompt_id": r["prompt_id"], "engine": r["engine"],
        "category": r["category"], "is_branded": bool(r["is_branded"]), "status": r["status"],
        "error_code": r["error_code"], "mentioned": flag(r["mentioned"]), "recommended": flag(r["recommended"]),
        "negative": flag(r["negative"]), "kasparro_cited": flag(r["kasparro_cited"]), "position": r["position"],
        "competitors": json.loads(r["competitors"]),
    } for r in rows]
    texts = {r["prompt_id"]: r["text"] for r in rows}

    blocks = {}
    for label, branded in (("branded", True), ("unbranded", False)):
        part = [r for r in results if r["is_branded"] == branded]
        blocks[label] = {
            "all": group_stats(part),
            "by_engine": _by(part, "engine"),
            "by_category": _by(part, "category"),
            "same_prompt_comparison": _same_prompt_comparison(part),
        }

    response_ids = [r["response_id"] for r in results]
    marks = ",".join("?" * len(response_ids))
    citation_rows = [dict(c) for c in conn.execute(
        f"SELECT response_id, url, domain, citation_type FROM citations WHERE response_id IN ({marks})",
        response_ids)] if response_ids else []

    return {
        "analysis_id": analysis_id,
        "llm_mode": run["llm_mode"], "model": run["model"],
        "versions": {"prompt": run["prompt_version"], "category": run["category_version"],
                     "scoring": run["scoring_version"]},
        "method": METHOD,
        # Coverage only. No score here: it would mix branded and unbranded prompts.
        "run_counts": {k: v for k, v in group_stats(results).items()
                       if k in ("total", "succeeded", "failed", "skipped", "coverage", "low_coverage")},
        "branded": blocks["branded"],
        "unbranded": blocks["unbranded"],
        "competitors": _competitors(results),
        "citations": citation_stats(citation_rows, response_ids),
        "per_prompt": _per_prompt(results, texts),
    }
