"""Deterministic score checks. Every expected number is worked out by hand in the comments."""
import sqlite3

import pytest

from app.config import get_settings
from app.scoring.aggregate import group_stats
from app.scoring.citations import citation_stats, normalise_url
from app.scoring.score import response_points
from tests.conftest import ANALYST
from tests.test_analysis import SCRIPT, run_analysis


def res(status="succeeded", mentioned=False, recommended=False, negative=False, cited=False):
    return {"status": status, "mentioned": mentioned, "recommended": recommended, "negative": negative,
            "kasparro_cited": cited}


# A: mentioned + recommended + not negative + cited = 30 + 40 + 20 + 10 = 100
# B: mentioned + negative                          = 30
# C: absent                                         = 0
# D: failed, E: skipped                            → no points
EXAMPLE = [
    res(mentioned=True, recommended=True, cited=True),
    res(mentioned=True, negative=True),
    res(),
    res(status="failed"),
    res(status="skipped"),
]


def test_response_points():
    assert response_points(EXAMPLE[0]) == {"parts": {"mentioned": 30, "recommended": 40, "not_negative": 20,
                                                     "cited": 10}, "total": 100}
    assert response_points(EXAMPLE[1])["total"] == 30
    assert response_points(EXAMPLE[2])["total"] == 0
    assert response_points(EXAMPLE[3]) is None and response_points(EXAMPLE[4]) is None


def test_not_negative_and_recommended_need_a_mention():
    # inconsistent input (recommended without mention) must not earn points
    assert response_points(res(recommended=True))["total"] == 0


def test_group_stats_hand_calculated():
    g = group_stats(EXAMPLE)
    assert (g["total"], g["succeeded"], g["failed"], g["skipped"]) == (5, 3, 1, 1)
    assert g["score"] == 43.3                 # (100 + 30 + 0) / 3 succeeded
    assert g["score_range"] == [32.5, 57.5]   # 130 / 4 (failed = 0) ... (130 + 100) / 4 (failed = 100)
    assert g["coverage"] == {"x": 3, "n": 5, "rate": 0.6}
    assert g["low_coverage"] is True          # 3/5 < 80%
    assert g["parts"]["mentioned"] == {"x": 2, "n": 3, "rate": 0.667}
    assert g["parts"]["recommended"]["x"] == 1 and g["parts"]["not_negative"]["x"] == 1
    assert g["parts"]["cited"]["x"] == 1 and g["negative"]["x"] == 1
    assert g["when_mentioned"]["negative"] == {"x": 1, "n": 2, "rate": 0.5}


def test_empty_and_all_failed_groups_do_not_divide_by_zero():
    empty = group_stats([])
    assert empty["score"] is None and empty["score_range"] is None and empty["low_coverage"] is False
    failed = group_stats([res(status="failed")] * 2)
    assert failed["score"] is None and failed["score_range"] == [0.0, 100.0]
    assert failed["parts"]["mentioned"] == {"x": 0, "n": 0, "rate": None}


@pytest.mark.parametrize("url, expected", [
    ("https://Kasparro.COM/#pricing", "https://kasparro.com"),
    ("https://kasparro.com/", "https://kasparro.com"),
    ("https://a.com/x?utm_source=gemini&id=7", "https://a.com/x?id=7"),
    ("https://a.com/x?UTM_Medium=y", "https://a.com/x"),
    ("http://[::1", "http://[::1"),  # broken URL: kept as is, no crash
])
def test_normalise_url(url, expected):
    assert normalise_url(url) == expected


def test_citation_stats_raw_vs_unique():
    rows = [
        {"response_id": "r1", "url": "https://kasparro.com/", "domain": "kasparro.com", "citation_type": "inline_hyperlink"},
        {"response_id": "r1", "url": "https://kasparro.com/#x", "domain": "kasparro.com", "citation_type": "sources_panel"},
        {"response_id": "r2", "url": "https://kasparro.com", "domain": None, "citation_type": "sources_panel"},
        {"response_id": "r2", "url": "https://www.b.com/p", "domain": "www.b.com", "citation_type": "sources_panel"},
    ]
    s = citation_stats(rows, ["r1", "r2", "r3"])
    assert s["occurrences"] == 4 and s["by_type"] == {"inline_hyperlink": 1, "sources_panel": 3}
    assert s["unique_urls_per_response_summed"] == 3   # r1: 1, r2: 2
    assert s["unique_urls_overall"] == 2               # kasparro.com, www.b.com/p
    assert s["kasparro_cited"] == {"x": 2, "n": 3, "rate": 0.667, "occurrences": 3}
    assert s["responses_with_citations"] == {"x": 2, "n": 3, "rate": 0.667}  # r3 has no citations
    assert s["top_domains"][0]["domain"] == "kasparro.com" and s["top_domains"][1]["domain"] == "b.com"
    assert s["status"] == "unverified"


def test_scores_from_a_real_run(client):
    run = run_analysis(client, SCRIPT)
    s = run["scores"]
    # branded prompt mini:001: r1 aimode 30 (mentioned, negative), r2 chatgpt 100, r3 gemini 50 (ranked, neutral)
    assert s["branded"]["all"]["score"] == 60.0
    assert s["branded"]["by_engine"]["chatgpt"]["score"] == 100.0
    assert s["branded"]["same_prompt_comparison"] == {
        "prompts": 1, "by_engine": {"aimode": 30.0, "chatgpt": 100.0, "gemini": 50.0}, "prompt_ids": ["mini:001"]}
    # unbranded mini:002: r4 absent 0, r5 absent but kasparro.com cited 10, r6 failed
    u = s["unbranded"]["all"]
    assert (u["score"], u["score_range"], u["low_coverage"]) == (5.0, [3.3, 36.7], True)
    assert u["parts"]["mentioned"] == {"x": 0, "n": 2, "rate": 0.0}
    assert s["unbranded"]["same_prompt_comparison"]["prompts"] == 0   # gemini failed there
    assert "score" not in s["run_counts"]                              # no mixed number anywhere
    assert s["citations"]["occurrences"] == 7 and s["citations"]["kasparro_cited"]["x"] == 2
    assert s["citations"]["unique_urls_per_response_summed"] == 6      # r2's two kasparro.com links are one URL
    names = {c["name"]: c for c in s["competitors"]}
    assert names["Profound"] == {"name": "Profound", "branded": 2, "unbranded": 2, "total": 4}
    row = s["per_prompt"][1]
    assert row["prompt_id"] == "mini:002" and row["engines"]["chatgpt"]["points"] == 10
    failed = row["engines"]["gemini"]
    assert (failed["status"], failed["mentioned"], failed["points"]) == ("failed", None, None)  # unknown, not "absent"


def test_scores_only_when_completed(client):
    run = run_analysis(client, SCRIPT, limit=1)
    assert run["scores"]["branded"]["all"]["total"] == 1
    conn = sqlite3.connect(get_settings().db_path)
    conn.execute("INSERT INTO analysis_runs (dataset_id, status, llm_mode, prompt_version, category_version, "
                 "scoring_version, started_at) VALUES (1, 'running', 'stub', 'v', 'v', 'v', 'now')")
    conn.commit()
    conn.close()
    assert "scores" not in client.get("/analyses/2", headers=ANALYST).json()
