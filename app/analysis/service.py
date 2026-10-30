"""Analysis runs: create a run, analyse one response, read results."""
import json
import re
import sqlite3

from app.analysis.categories import CATEGORY_VERSION, categorize
from app.analysis.preprocess import (DOMAIN_LIKE, find_mention, kasparro_cited, named_in_prose, prose_only,
                                     quote_in_text, strip_url_list)
from app.config import Settings
from app.db import now
from app.errors import AppError
from app.llm.client import Budget, EvidenceError, LLMClient, LogFn, call_with_retries
from app.llm.prompts import PROMPT_VERSION, ClassifyOutput, build_messages
from app.scoring.score import SCORING_VERSION

# Text that talks to the classifier instead of describing Kasparro (prompt injection inside an answer).
INSTRUCTION = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) instructions|\b(respond|reply) with\b|"
    r"\bmark kasparro as\b|[{,]\s*[\"'](recommended|negative)[\"']\s*:", re.IGNORECASE)

# Same company, different spellings → one name. Keys are lowercase.
ALIASES = {
    "otterly": "Otterly", "otterly.ai": "Otterly", "otterly ai": "Otterly", "otterlyai": "Otterly",
    "peec": "Peec AI", "peec ai": "Peec AI", "peec.ai": "Peec AI",
    "athenahq": "AthenaHQ", "athena hq": "AthenaHQ", "athena": "AthenaHQ",
    "profound": "Profound", "dageno": "Dageno AI", "dageno ai": "Dageno AI",
}
# Not competitors: AI engines, search, review sites and generic terms the model sometimes lists.
NOT_COMPETITORS = {"chatgpt", "openai", "gemini", "claude", "perplexity", "copilot", "google", "bing",
                   "google ai mode", "g2", "capterra", "reddit", "seo", "geo", "aeo", "aiso"}


def normalise_competitors(names: list[str], answer: str | None = None) -> list[str]:
    """Clean the model's competitor list. With `answer`, a name must appear in the answer's prose:
    the model also lists websites that are only cited as sources (eval failure F3)."""
    prose = prose_only(answer) if answer is not None else None
    out, seen = [], set()
    for name in names:
        name = name.strip()
        key = name.lower()
        if not name or "kasparro" in key or key in NOT_COMPETITORS:
            continue
        canonical = ALIASES.get(key, name)  # "Otterly.AI" → "Otterly" before any domain check
        if prose is not None:
            # "fundraiseinsider.com" → look for "fundraiseinsider" in the prose; a real brand like "Peec.ai"
            # is still found because its name appears outside links.
            check = re.sub(r"\.[a-z]{2,4}(/\S*)?$", "", canonical, flags=re.IGNORECASE) \
                if DOMAIN_LIKE.fullmatch(canonical) else canonical
            if not named_in_prose(check, prose):
                continue
        if canonical.lower() not in seen:
            seen.add(canonical.lower())
            out.append(canonical)
    return out


def kasparro_position(ranked_list: list[str] | None) -> int | None:
    for i, item in enumerate(ranked_list or [], start=1):
        if "kasparro" in item.lower():
            return i
    return None


def analyse_response(response: dict, question: str, citations: list[dict], client: LLMClient,
                     settings: Settings, budget: Budget, log: LogFn | None = None) -> dict:
    """One response → one result dict with status succeeded / failed / skipped. Never raises on bad output."""
    answer = response["answer_text"]
    result = {
        "response_id": response["response_id"], "status": None, "error_code": None, "skip_reason": None,
        "mentioned": None, "recommended": None, "negative": None, "evidence": {}, "competitors": [],
        "ranked_list": None, "position": None, "kasparro_cited": kasparro_cited(citations),
    }
    if response.get("capture_status", "captured") != "captured":
        return {**result, "status": "skipped", "skip_reason": "not_captured"}
    cleaned = strip_url_list(answer)
    if not cleaned.strip():
        return {**result, "status": "skipped", "skip_reason": "empty_after_cleaning"}

    mentioned, mention_quote = find_mention(cleaned)

    def validate(data: ClassifyOutput) -> None:
        if not mentioned:
            return  # labels are forced false below, so their quotes do not matter
        for label in ("recommended", "negative"):
            if not getattr(data, label):
                continue
            quote = getattr(data, f"{label}_quote")
            # An instruction aimed at the classifier is never evidence (eval failure F4, case s01).
            if not quote_in_text(quote, answer) or INSTRUCTION.search(quote):
                raise EvidenceError(label)

    outcome = call_with_retries(client, response["response_id"], build_messages(question, cleaned),
                                settings, budget, validate, log)
    if outcome.status == "failed":
        return {**result, "status": "failed", "error_code": outcome.error_code}

    data = outcome.data
    recommended = bool(mentioned and data.recommended)
    negative = bool(mentioned and data.negative)
    evidence = {}
    if mentioned:
        evidence["mentioned"] = mention_quote
    if recommended:
        evidence["recommended"] = data.recommended_quote
    if negative:
        evidence["negative"] = data.negative_quote
    return {
        **result, "status": "succeeded", "mentioned": mentioned, "recommended": recommended,
        "negative": negative, "evidence": evidence, "competitors": normalise_competitors(data.competitors, cleaned),
        "ranked_list": data.ranked_list, "position": kasparro_position(data.ranked_list),
    }


def create_run(conn: sqlite3.Connection, dataset_id: int, limit: int | None, client: LLMClient) -> int:
    with conn:
        conn.execute("BEGIN IMMEDIATE")  # the "already running?" check and the insert happen under one lock
        if not conn.execute("SELECT 1 FROM datasets WHERE id = ?", (dataset_id,)).fetchone():
            raise AppError(404, "dataset_not_found", f"Dataset {dataset_id} does not exist.")
        if not conn.execute("SELECT 1 FROM responses WHERE dataset_id = ?", (dataset_id,)).fetchone():
            raise AppError(422, "dataset_empty", f"Dataset {dataset_id} has no responses to analyse.")
        running = conn.execute("SELECT id FROM analysis_runs WHERE status = 'running'").fetchone()
        if running:
            raise AppError(409, "analysis_running", "Another analysis is still running.",
                           {"analysis_id": running["id"]})
        run_id = conn.execute(
            "INSERT INTO analysis_runs (dataset_id, status, llm_mode, model, prompt_version, category_version, "
            'scoring_version, "limit", started_at) VALUES (?, \'running\', ?, ?, ?, ?, ?, ?, ?)',
            (dataset_id, client.mode, client.model, PROMPT_VERSION, CATEGORY_VERSION, SCORING_VERSION, limit, now()),
        ).lastrowid
        # Categories always come from the current rules, whatever was stored at import time.
        for row in conn.execute("SELECT prompt_id, text FROM prompts").fetchall():
            conn.execute("UPDATE prompts SET category = ? WHERE prompt_id = ?", (categorize(row["text"]), row["prompt_id"]))
    return run_id


RESULT_COLUMNS = ("status", "error_code", "skip_reason", "mentioned", "recommended", "negative", "evidence",
                  "competitors", "ranked_list", "position", "kasparro_cited")


def _bool(v):
    return None if v is None else bool(v)


def get_run(conn: sqlite3.Connection, run_id: int, include_results: bool = True) -> dict:
    run = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        raise AppError(404, "analysis_not_found", f"Analysis {run_id} does not exist.")
    out = {
        "analysis_id": run["id"], "dataset_id": run["dataset_id"], "status": run["status"],
        "llm_mode": run["llm_mode"], "model": run["model"],
        "versions": {"prompt": run["prompt_version"], "category": run["category_version"],
                     "scoring": run["scoring_version"]},
        "limit": run["limit"], "started_at": run["started_at"], "finished_at": run["finished_at"],
        "counts": json.loads(run["counts"]),
        "llm": {"calls": run["llm_calls"], "seconds": round(run["llm_seconds"], 1), "cost_usd": run["cost_usd"]},
    }
    if include_results:
        rows = conn.execute(
            "SELECT rr.*, r.prompt_id, r.engine, p.category, p.is_branded FROM response_results rr "
            "JOIN responses r ON r.response_id = rr.response_id JOIN prompts p ON p.prompt_id = r.prompt_id "
            "WHERE rr.analysis_id = ? ORDER BY r.prompt_id, r.engine", (run_id,)).fetchall()
        out["results"] = [{
            "response_id": r["response_id"], "prompt_id": r["prompt_id"], "engine": r["engine"],
            "category": r["category"], "is_branded": bool(r["is_branded"]),
            "status": r["status"], "error_code": r["error_code"], "skip_reason": r["skip_reason"],
            "mentioned": _bool(r["mentioned"]), "recommended": _bool(r["recommended"]),
            "negative": _bool(r["negative"]), "evidence": json.loads(r["evidence"]),
            "competitors": json.loads(r["competitors"]),
            "ranked_list": json.loads(r["ranked_list"]) if r["ranked_list"] else None,
            "position": r["position"], "kasparro_cited": _bool(r["kasparro_cited"]),
        } for r in rows]
    return out
