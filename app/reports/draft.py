"""Draft report built by code: scores plus 3 diagnostic drafts (pattern + evidence).
The analyst writes explanations, what would test them, and the 3 remedies."""
import json
import re
import sqlite3

from app.analysis.preprocess import quote_in_text, sentence_with, strip_url_list
from app.scoring.aggregate import build_scores

ENGINE_NAMES = {"aimode": "AI Mode", "chatgpt": "ChatGPT", "gemini": "Gemini"}
MAX_EVIDENCE = 5


def _frac(r: dict) -> str:
    return f"{r['x']}/{r['n']}"


def _results(conn: sqlite3.Connection, analysis_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT rr.response_id, rr.status, rr.evidence, rr.competitors, r.engine, r.answer_text, r.prompt_id, "
        "p.is_branded FROM response_results rr JOIN responses r ON r.response_id = rr.response_id "
        "JOIN prompts p ON p.prompt_id = r.prompt_id WHERE rr.analysis_id = ? ORDER BY r.prompt_id, r.engine",
        (analysis_id,)).fetchall()
    return [dict(r) | {"evidence": json.loads(r["evidence"]), "competitors": json.loads(r["competitors"])}
            for r in rows]


FIRST_WORD = re.compile(r"\w")


def _sentence_ref(r: dict, pattern: re.Pattern) -> dict | None:
    """Evidence ref for the sentence matching `pattern`, only if it passes the validator's quote check."""
    sentence = sentence_with(strip_url_list(r["answer_text"]), pattern)
    if sentence and quote_in_text(sentence, r["answer_text"]):
        return {"response_id": r["response_id"], "quote": sentence}
    return None


def _spread(refs: list[dict], engine_of: dict) -> list[dict]:
    """Prefer evidence from different engines first, then fill up to MAX_EVIDENCE."""
    seen, first, rest = set(), [], []
    for ref in refs:
        engine = engine_of[ref["response_id"]]
        (rest if engine in seen else first).append(ref)
        seen.add(engine)
    return (first + rest)[:MAX_EVIDENCE]


def _unbranded_inclusion(scores: dict, results: list[dict], engine_of: dict) -> dict:
    block = scores["unbranded"]
    a = block["all"]
    by_engine = ", ".join(f"{ENGINE_NAMES[e]} {_frac(g['parts']['mentioned'])}" for e, g in block["by_engine"].items())
    top = [c for c in scores["competitors"] if c["unbranded"]][:5]
    named = ", ".join(f"{c['name']} ({c['unbranded']})" for c in top) or "none"
    pattern = (f"Kasparro is named in {_frac(a['parts']['mentioned'])} succeeded unbranded answers ({by_engine}; "
               f"{a['failed']} failed, {a['skipped']} skipped). Most-named alternatives in unbranded answers: {named}.")

    unbranded = [r for r in results if not r["is_branded"] and r["status"] == "succeeded"]
    refs = [{"response_id": r["response_id"], "quote": r["evidence"]["mentioned"]}
            for r in unbranded if "mentioned" in r["evidence"]]
    if not refs:  # absent everywhere: show who is named instead
        for r in unbranded:
            for name in r["competitors"]:
                ref = _sentence_ref(r, re.compile(re.escape(name), re.IGNORECASE))
                if ref:
                    refs.append(ref)
                    break
    if not refs:  # no competitors either: show how the answers open
        refs = [ref for r in unbranded if (ref := _sentence_ref(r, FIRST_WORD))]
    return {"id": "D1", "title": "Unbranded discovery: is Kasparro included?", "pattern": pattern,
            "explanation": "", "test_evidence": "", "evidence": _spread(refs, engine_of)}


def _branded_description(scores: dict, results: list[dict], engine_of: dict) -> dict:
    block = scores["branded"]
    a = block["all"]
    wm = a["when_mentioned"]
    by_engine = ", ".join(
        f"{ENGINE_NAMES[e]} negative {_frac(g['when_mentioned']['negative'])}, "
        f"recommended {_frac(g['when_mentioned']['recommended'])}" for e, g in block["by_engine"].items())
    pattern = (f"On branded prompts Kasparro is mentioned in {_frac(a['parts']['mentioned'])} succeeded answers. "
               f"Of the answers that mention it, {_frac(wm['negative'])} describe it negatively and "
               f"{_frac(wm['recommended'])} recommend it ({by_engine}; {a['failed']} failed).")
    branded = [r for r in results if r["is_branded"] and r["status"] == "succeeded"]
    negative = [{"response_id": r["response_id"], "quote": r["evidence"]["negative"]}
                for r in branded if "negative" in r["evidence"]]
    recommended = [{"response_id": r["response_id"], "quote": r["evidence"]["recommended"]}
                   for r in branded if "recommended" in r["evidence"]]
    refs = _spread(negative, engine_of)[:3] + _spread(recommended, engine_of)[:2]
    if not refs:  # nothing negative or recommended: show how Kasparro is mentioned
        refs = _spread([{"response_id": r["response_id"], "quote": r["evidence"]["mentioned"]}
                        for r in branded if "mentioned" in r["evidence"]], engine_of)
    return {"id": "D2", "title": "Branded answers: how Kasparro is described", "pattern": pattern,
            "explanation": "", "test_evidence": "", "evidence": refs}


def _engine_gap(scores: dict, results: list[dict], engine_of: dict) -> dict:
    title = "Engine differences on the same prompts"
    options = []
    for label in ("branded", "unbranded"):
        comp = scores[label]["same_prompt_comparison"]
        values = [v for v in comp["by_engine"].values() if v is not None]
        if values:
            options.append((max(values) - min(values), label, comp))
    if not options:
        return {"id": "D3", "title": title, "explanation": "", "test_evidence": "", "evidence": [],
                "pattern": "No prompt has a succeeded answer from all three engines, so engines cannot be compared."}

    gap, label, comp = max(options)
    ranked = sorted(comp["by_engine"].items(), key=lambda kv: -kv[1])
    averages = ", ".join(f"{ENGINE_NAMES[e]} {v}" for e, v in ranked)
    pattern = (f"On the {comp['prompts']} {label} prompts that all three engines answered successfully, the average "
               f"score is {averages} (gap {round(gap, 1)} points).")

    # Evidence: Kasparro quotes from the best and worst engine on the shared prompts.
    best, worst = ranked[0][0], ranked[-1][0]
    shared = set(comp["prompt_ids"])
    refs = []
    for engine in (best, worst):
        for r in results:
            if r["prompt_id"] in shared and r["engine"] == engine and r["status"] == "succeeded":
                for key in ("negative", "recommended", "mentioned"):
                    if key in r["evidence"]:
                        refs.append({"response_id": r["response_id"], "quote": r["evidence"][key]})
                        break
            if sum(engine_of[x["response_id"]] == engine for x in refs) >= 2:
                break
    return {"id": "D3", "title": title, "pattern": pattern, "explanation": "", "test_evidence": "",
            "evidence": refs[:MAX_EVIDENCE]}


def build_draft(conn: sqlite3.Connection, analysis_id: int) -> dict:
    scores = build_scores(conn, analysis_id)
    results = _results(conn, analysis_id)
    engine_of = {r["response_id"]: r["engine"] for r in results}
    return {
        "scores": scores,
        "diagnostics": [
            _unbranded_inclusion(scores, results, engine_of),
            _branded_description(scores, results, engine_of),
            _engine_gap(scores, results, engine_of),
        ],
        "remedies": [],
        "notes": "",
    }
