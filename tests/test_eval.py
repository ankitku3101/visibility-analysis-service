"""Tests for the eval harness itself: grader math, baseline rules and an end-to-end stub run."""
import json
from pathlib import Path

from eval import baseline, grader
from eval.run_eval import main

LABELS = Path(__file__).parent.parent / "eval" / "cases" / "labels_v1.json"


def pred(status="succeeded", mentioned=False, recommended=False, negative=False, competitors=(), position=None,
         cited=False):
    return {"status": status, "mentioned": mentioned, "recommended": recommended, "negative": negative,
            "competitors": list(competitors), "position": position, "kasparro_cited": cited}


def exp(mentioned=False, recommended=False, negative=False, competitors=(), position=None, cited=False):
    return {"mentioned": mentioned, "recommended": recommended, "negative": negative,
            "competitors": list(competitors), "position": position, "cited": cited}


def test_label_metrics_known_counts():
    pairs = [
        (exp(mentioned=True, negative=True), pred(mentioned=True, negative=True)),   # TP negative
        (exp(mentioned=True), pred(mentioned=True, negative=True)),                  # FP negative
        (exp(mentioned=True, negative=True), pred(mentioned=True)),                  # FN negative
        (exp(mentioned=True, negative=True), pred(status="failed")),                 # failed → FN, not TN
        (exp(), pred(status="failed")),                                              # failed, label false → not TN
    ]
    m = grader.label_metrics(pairs)["negative"]
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 2, 0)
    assert (m["precision"], m["recall"]) == (0.5, 0.333)


def test_competitor_metrics_loose_names():
    pairs = [(exp(competitors=["Semrush", "Otterly", "Profound"]),
              pred(competitors=["Semrush (AI Visibility Toolkit)", "OtterlyAI", "SEO"]))]
    assert grader.competitor_metrics(pairs) == {"tp": 2, "fp": 1, "fn": 1, "precision": 0.667, "recall": 0.667}


def test_baseline_rules():
    out = baseline.classify("q", "Kasparro is not widely recognized yet. Try Profound or Peec AI.", [])
    assert (out["mentioned"], out["negative"], out["recommended"]) == (True, True, False)
    assert out["competitors"] == ["Profound", "Peec AI"]
    url_only = baseline.classify("q", "Use Profound.\n\nCitations:\n[1] https://kasparro.com/", [{"domain": "kasparro.com"}])
    assert (url_only["mentioned"], url_only["kasparro_cited"]) == (False, True)


def test_regression_rule_not_recommended():
    from eval.run_eval import regression_ok
    e = exp(mentioned=True)
    assert regression_ok("not_recommended", e, pred(status="failed"))              # failed safely
    assert regression_ok("not_recommended", e, pred(mentioned=True))
    assert not regression_ok("not_recommended", e, pred(mentioned=True, recommended=True))
    assert not regression_ok(None, e, pred(status="failed"))                       # default: exact labels


def test_failure_log_regression_tests_exist():
    """Every regression test named in the failure log must exist, so the log cannot point at nothing."""
    import importlib
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    for f in labels["failure_log"]:
        assert f["regression_case_ids"] or f.get("regression_tests"), f["id"]
        for ref in f.get("regression_tests", []):
            path, name = ref.split("::", 1)
            name = name.split("::")[0].split("[")[0]  # "Class::method" → Class, "test[param]" → test
            module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
            assert hasattr(module, name), ref


def test_labels_file_is_consistent():
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    assert all(s["ok"] for s in grader.score_math_check(labels["cases"]))
    real = [c for c in labels["cases"] if not c["synthetic"]]
    assert len(real) >= 8 and len({c["engine"] for c in real}) == 3
    assert len({c["category"] for c in real}) >= 4
    assert sum(c["synthetic"] for c in labels["cases"]) == 2
    assert {c["split"] for c in labels["cases"]} == {"tuning", "final"}


def test_run_eval_stub_writes_unverified_report(tmp_path):
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    labels["cases"] = [c for c in labels["cases"] if c["synthetic"]]   # no pack needed
    labels["status"] = "proposed"                                       # report must warn about this
    labels["failure_log"] = []
    labels["evidence_probes"] = [labels["evidence_probes"][3]]          # unknown-response probe needs no pack
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    result = main(["--labels", str(path), "--out", str(tmp_path / "out")])
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "UNVERIFIED" in report and "not yet confirmed" in report
    assert result["counts"]["llm"] == {"eligible": 2, "succeeded": 2, "failed": 0, "skipped": 0}
    assert result["evidence"][0]["ok"]
