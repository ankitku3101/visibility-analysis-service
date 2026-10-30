"""Run the evaluation and write a readable comparison report.

    python -m eval.run_eval                  # final split, current LLM_MODE
    python -m eval.run_eval --split tuning   # cases used while tuning the prompt
    LLM_MODE=local python -m eval.run_eval   # real model (Ollama)
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.analysis.categories import CATEGORY_VERSION
from app.analysis.service import analyse_response
from app.config import get_settings
from app.ingest.loader import load_pack
from app.errors import AppError
from app.llm.client import Budget, get_client, preflight
from app.llm.prompts import PROMPT_VERSION
from app.scoring.score import SCORING_VERSION
from eval import baseline, grader

ROOT = Path(__file__).parent
DEFAULT_LABELS = ROOT / "cases" / "labels_v1.json"
DEFAULT_OUT = ROOT / "results"


def load_inputs(labels: dict, pack_dir: str) -> dict:
    """case_id → {question, response(dict), citations} for real and synthetic cases."""
    needs_pack = any(not c["synthetic"] for c in labels["cases"])
    pack = load_pack(pack_dir) if needs_pack else {"prompts": [], "responses": [], "citations": []}
    questions = {p["prompt_id"]: p["text"] for p in pack["prompts"]}
    responses = {r["response_id"]: r for r in pack["responses"]}
    inputs = {}
    for c in labels["cases"]:
        if c["synthetic"]:
            inputs[c["case_id"]] = {
                "question": c["question"],
                "response": {"response_id": c["case_id"], "answer_text": c["answer_text"], "capture_status": "captured"},
                "citations": c.get("citations", []),
            }
        else:
            r = responses[c["response_id"]]
            inputs[c["case_id"]] = {
                "question": questions[r["prompt_id"]], "response": r,
                "citations": [x for x in pack["citations"] if x["response_id"] == c["response_id"]],
            }
    return inputs


def mark(ok) -> str:
    return "-" if ok is None else ("✓" if ok else "✗")


def short(pred: dict) -> str:
    if pred["status"] != "succeeded":
        return f"{pred['status']}: {pred.get('error_code') or pred.get('skip_reason')}"
    flags = [k[:3] for k in ("mentioned", "recommended", "negative") if pred[k]]
    return f"{'+'.join(flags) or 'absent'}; pos={pred['position']}; comp={len(pred['competitors'])}"


def fmt_metrics(name: str, m: dict) -> str:
    return f"| {name} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']} | {m['recall']} |"


def write_report(path: Path, r: dict) -> None:
    unverified = r["mode"] in ("replay", "stub")
    lines = [
        "# Evaluation report", "",
        f"- Run at: {r['run_at']} | split: **{r['split']}** | cases: {len(r['cases'])}",
        f"- LLM mode: **{r['mode']}** | model: {r['model']} | versions: prompt {PROMPT_VERSION}, "
        f"category {CATEGORY_VERSION}, scoring {SCORING_VERSION}",
        f"- Labels: {r['labels_status']} ({r['labels_file']})",
        f"- LLM calls: {r['llm_calls']} | time: {r['seconds']} s | cost: $0 (local)",
    ]
    if unverified:
        lines += ["", f"> **Model quality: UNVERIFIED.** Mode `{r['mode']}` replays or fakes outputs. It checks the "
                      "pipeline, not live model correctness, variability, cost or latency. "
                      "Run `LLM_MODE=local python -m eval.run_eval` for real-model numbers."]
    if not r["labels_status"].startswith("confirmed"):
        lines += ["", "> **Labels are not yet confirmed by the developer.** Numbers below are provisional."]
    if r["split"] == "final" and r["final_split_history"]:
        lines += ["", "## Held-out status", "", *[f"- {x}" for x in r["final_split_history"]]]
    if r["label_corrections"]:
        lines += ["", "## Label corrections (disclosed)", "", *[f"- {x}" for x in r["label_corrections"]]]
    lines += ["", "## Counts", "", "| Path | eligible | succeeded | failed | skipped |", "|---|---|---|---|---|"]
    for name in ("llm", "baseline"):
        c = r["counts"][name]
        lines.append(f"| {name} | {c['eligible']} | {c['succeeded']} | {c['failed']} | {c['skipped']} |")
    lines += ["", "## Labels: LLM vs rule-based baseline", "",
              "| Label / path | TP | FP | FN | precision | recall |", "|---|---|---|---|---|---|"]
    for label in grader.LABELS:
        for name in ("llm", "baseline"):
            lines.append(fmt_metrics(f"{label} / {name}", r["labels"][name][label]))
    lines += ["", "| Other | LLM | baseline |", "|---|---|---|"]
    for name, key in (("competitors precision", "precision"), ("competitors recall", "recall")):
        lines.append(f"| {name} | {r['competitors']['llm'][key]} | {r['competitors']['baseline'][key]} |")
    pa, pb = r["position"]["llm"], r["position"]["baseline"]
    lines.append(f"| position exact | {pa['x']}/{pa['n']} | {pb['x']}/{pb['n']} |")
    q = r["quotes_found"]
    lines.append(f"| LLM quotes found in answer | {q['x']}/{q['n']} | n/a |")

    lines += ["", "## Per case", "", "| case | split | engine | expected | LLM | baseline | LLM ok | base ok |",
              "|---|---|---|---|---|---|---|---|"]
    for c in r["cases"]:
        lines.append(f"| {c['case_id']}{' (synthetic)' if c['synthetic'] else ''} | {c['split']} | {c['engine']} | "
                     f"{short(c['expected_short'])} | {short(c['llm'])} | {short(c['baseline'])} | "
                     f"{mark(c['llm_ok'])} | {mark(c['baseline_ok'])} |")

    lines += ["", "## Score math (hand-computed points vs score-v1)", ""]
    bad = [s for s in r["score_math"] if not s["ok"]]
    lines.append(f"{len(r['score_math']) - len(bad)}/{len(r['score_math'])} cases match." +
                 ("" if not bad else f" Mismatches: {bad}"))
    lines += ["", "## Evidence checks (real report validator on crafted claims)", "",
              "| probe | expected | found | ok |", "|---|---|---|---|"]
    for e in r["evidence"]:
        lines.append(f"| {e['probe']} | {e['expected']} | {e['found']} | {mark(e['ok'])} |")
    lines += ["", "## Failure → fix → regression", ""]
    for f in r["failure_log"]:
        lines += [f"**{f['id']}** — {f['failure']}", f"- Diagnosis: {f['diagnosis']}", f"- Change: {f['change']}"]
        if f["regression"]:
            lines.append(f"- Regression check ({f.get('pass_if') or 'exact labels'}): "
                         + ", ".join(f"{cid} {mark(ok)}" for cid, ok in f["regression"]))
        if f.get("regression_tests"):
            lines.append("- Regression tests (run by `pytest`): " + ", ".join(f"`{t}`" for t in f["regression_tests"]))
        lines.append("")
    if r["known_disagreements"]:
        lines += ["## Known disagreements (not tuned away)", "", *[f"- {x}" for x in r["known_disagreements"]], ""]
    lines += ["## Limits of this evaluation", "", *[f"- {x}" for x in r["limits"]], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def case_ok(exp: dict, pred: dict) -> bool:
    if pred["status"] != "succeeded":
        return False
    return all(grader._expected(exp, k) == grader._value(pred, k) for k in grader.LABELS)


def regression_ok(rule: str | None, exp: dict, pred: dict) -> bool:
    """Default: exact labels. 'not_recommended': the case must never end up as a recommendation
    (failing safely without a label also passes; used for the prompt-injection case)."""
    if rule == "not_recommended":
        return not (pred["status"] == "succeeded" and pred["recommended"])
    return case_ok(exp, pred)


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["final", "tuning", "all"], default="final")
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    settings = get_settings()
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    inputs = load_inputs(labels, settings.pack_dir)
    regression_ids = {cid for f in labels.get("failure_log", []) for cid in f["regression_case_ids"]}
    in_split = [c for c in labels["cases"] if args.split == "all" or c["split"] == args.split]
    to_run = in_split + [c for c in labels["cases"] if c["case_id"] in regression_ids and c not in in_split]

    # The eval keeps its own recordings (replay/eval/...), so the full 150-response run can never
    # overwrite the outputs behind eval/results/report.md.
    client = get_client(settings.model_copy(update={"replay_dir": str(Path(settings.replay_dir) / "eval")}))
    try:
        preflight(client)
    except AppError as e:
        sys.exit(f"Cannot run the eval: {e.message}")
    budget = Budget(limit=settings.llm_max_calls)
    started = time.perf_counter()
    llm, base = {}, {}
    for c in to_run:
        x = inputs[c["case_id"]]
        llm[c["case_id"]] = analyse_response(x["response"], x["question"], x["citations"], client, settings, budget)
        base[c["case_id"]] = baseline.classify(x["question"], x["response"]["answer_text"], x["citations"])
        print(f"  {c['case_id']}: llm {short(llm[c['case_id']])}", file=sys.stderr)

    pairs_llm = [(c["expected"], llm[c["case_id"]]) for c in in_split]
    pairs_base = [(c["expected"], base[c["case_id"]]) for c in in_split]
    answers = {x["response"]["response_id"]: x["response"]["answer_text"] for x in inputs.values()}
    result = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "split": args.split,
        "mode": client.mode, "model": client.model, "labels_file": Path(args.labels).name,
        "labels_status": labels.get("status", "unknown"),
        "llm_calls": budget.used, "seconds": round(time.perf_counter() - started, 1),
        "counts": {"llm": grader.counts([llm[c["case_id"]] for c in in_split]),
                   "baseline": grader.counts([base[c["case_id"]] for c in in_split])},
        "labels": {"llm": grader.label_metrics(pairs_llm), "baseline": grader.label_metrics(pairs_base)},
        "competitors": {"llm": grader.competitor_metrics(pairs_llm), "baseline": grader.competitor_metrics(pairs_base)},
        "position": {"llm": grader.position_accuracy(pairs_llm), "baseline": grader.position_accuracy(pairs_base)},
        "quotes_found": grader.quotes_found(answers, [llm[c["case_id"]] for c in in_split]),
        "score_math": grader.score_math_check(labels["cases"]),
        "evidence": grader.evidence_checks(answers, labels.get("evidence_probes", [])),
        "failure_log": [f | {"regression": [
            (cid, regression_ok(f.get("pass_if"), next(c for c in labels["cases"] if c["case_id"] == cid)["expected"],
                                llm[cid])) for cid in f["regression_case_ids"]]}
            for f in labels.get("failure_log", [])],
        "limits": labels.get("limits", []),
        "known_disagreements": labels.get("known_disagreements", []),
        "label_corrections": labels.get("label_corrections", []),
        "final_split_history": labels.get("final_split_history", []),
        "cases": [{
            "case_id": c["case_id"], "split": c["split"], "synthetic": c["synthetic"], "engine": c.get("engine", "-"),
            "expected_short": {"status": "succeeded", **c["expected"]},
            "llm": llm[c["case_id"]], "baseline": base[c["case_id"]],
            "llm_ok": case_ok(c["expected"], llm[c["case_id"]]), "baseline_ok": case_ok(c["expected"], base[c["case_id"]]),
        } for c in in_split],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.split == "final" else f"_{args.split}"
    (out / f"results{suffix}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str),
                                               encoding="utf-8")
    write_report(out / f"report{suffix}.md", result)
    print(f"Wrote {out / f'report{suffix}.md'}", file=sys.stderr)
    return result


if __name__ == "__main__":
    main()
