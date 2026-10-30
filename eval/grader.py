"""Code-only grader. It compares predictions with human labels; no LLM judges anything here."""
import re

from app.reports.models import ReportContent
from app.reports.validate import find_problems
from app.scoring.score import response_points

LABELS = ("mentioned", "recommended", "negative", "absent", "cited")


def _value(pred: dict, label: str):
    if pred["status"] != "succeeded":
        return None
    if label == "absent":
        return not pred["mentioned"]
    if label == "cited":
        return bool(pred["kasparro_cited"])
    return bool(pred[label])


def _expected(exp: dict, label: str) -> bool:
    return (not exp["mentioned"]) if label == "absent" else bool(exp[label])


def label_metrics(pairs: list[tuple[dict, dict]]) -> dict:
    """pairs = (expected, prediction). A failed prediction is a miss (FN) when the label is true,
    and is never counted as a correct "false" (it is listed separately as failed)."""
    out = {}
    for label in LABELS:
        tp = fp = fn = tn = 0
        for exp, pred in pairs:
            e, p = _expected(exp, label), _value(pred, label)
            if p is None:
                fn += e
                continue
            tp += e and p
            fp += (not e) and p
            fn += e and not p
            tn += (not e) and not p
        out[label] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                      "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                      "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    return out


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _same_tool(a: str, b: str) -> bool:
    """'Semrush (AI Visibility Toolkit)' matches 'Semrush'; 'OtterlyAI' matches 'Otterly'."""
    ka, kb = _key(a), _key(b)
    return bool(ka and kb) and (ka in kb or kb in ka)


def competitor_metrics(pairs: list[tuple[dict, dict]]) -> dict:
    tp = fp = fn = 0
    for exp, pred in pairs:
        expected = list(exp["competitors"])
        predicted = list(pred["competitors"]) if pred["status"] == "succeeded" else []
        matched = 0
        for p in predicted:
            hit = next((e for e in expected if _same_tool(p, e)), None)
            if hit is not None:
                expected.remove(hit)
                matched += 1
        tp += matched
        fp += len(predicted) - matched
        fn += len(expected)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def position_accuracy(pairs: list[tuple[dict, dict]]) -> dict:
    correct = sum(pred["status"] == "succeeded" and pred["position"] == exp["position"] for exp, pred in pairs)
    return {"x": correct, "n": len(pairs)}


def counts(preds: list[dict]) -> dict:
    return {"eligible": len(preds),
            **{s: sum(p["status"] == s for p in preds) for s in ("succeeded", "failed", "skipped")}}


def score_math_check(cases: list[dict]) -> list[dict]:
    """The hand-written points of every case must equal what score-v1 computes from the same labels."""
    rows = []
    for c in cases:
        e = c["expected"]
        computed = response_points({"status": "succeeded", "mentioned": e["mentioned"], "recommended": e["recommended"],
                                    "negative": e["negative"], "kasparro_cited": e["cited"]})["total"]
        rows.append({"case_id": c["case_id"], "hand": e["points"], "computed": computed, "ok": computed == e["points"]})
    return rows


def evidence_checks(answers: dict[str, str], probes: list[dict]) -> list[dict]:
    """Runs the real report validator on crafted claims. Each probe says which problem codes it must produce."""
    rows = []
    for probe in probes:
        content = ReportContent.model_validate({"scores": {}, **probe["content"]})
        found = sorted({p["code"] for p in find_problems(answers, content, complete=False)})
        rows.append({"probe": probe["name"], "expected": sorted(probe["expect"]), "found": found,
                     "ok": found == sorted(probe["expect"])})
    return rows


def quotes_found(answers: dict[str, str], preds: list[dict]) -> dict:
    """Every quote behind a true label must be in its answer (should always hold: the pipeline checks it)."""
    from app.analysis.preprocess import quote_in_text
    total = ok = 0
    for p in preds:
        for quote in (p.get("evidence") or {}).values():
            total += 1
            ok += quote_in_text(quote, answers[p["response_id"]])
    return {"x": ok, "n": total}
