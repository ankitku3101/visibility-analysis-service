import json
from collections import Counter
from pathlib import Path

import pytest

from app.analysis.categories import categorize, is_branded

REAL_PROMPTS = Path(__file__).parent.parent / "data" / "prompts.jsonl"


@pytest.mark.parametrize("text, expected", [
    ("is kasparro better than profound?", "comparison"),
    ("how much does it cost?", "pricing"),
    ("how long does setup take?", "onboarding_access"),
    ("what software tools measure AI visibility?", "discovery"),
    ("is it a legit platform?", "trust_results"),
    ("does it track copilot?", "features_fit"),
])
def test_categorize(text, expected):
    assert categorize(text) == expected


def test_is_branded():
    assert is_branded("Is KASPARRO legit?")
    assert not is_branded("what tools track AI answers?")


@pytest.mark.skipif(not REAL_PROMPTS.is_file(), reason="real pack not present")
def test_real_prompt_category_counts():
    texts = [json.loads(line)["text"] for line in REAL_PROMPTS.read_text(encoding="utf-8").splitlines() if line]
    assert sum(is_branded(t) for t in texts) == 25
    assert Counter(categorize(t) for t in texts) == {
        "comparison": 7, "discovery": 6, "features_fit": 10,
        "onboarding_access": 7, "pricing": 7, "trust_results": 13,
    }
