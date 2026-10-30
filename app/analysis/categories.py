"""Prompt categories (cat-v1): keyword rules on the question text, first match wins."""
import re

CATEGORY_VERSION = "cat-v1"

RIVALS = r"profound|otterly|athenahq|peec|dageno"

RULES = [
    ("comparison", rf"\b(vs\.?|versus|better than|compare|compared|faster than|more trustworthy|{RIVALS})\b"),
    ("pricing", r"\b(cost|costs|price|priced|overpriced|worth the money|retainers?|fees|value)\b"),
    ("onboarding_access", r"\b(setup|set up|onboarding|cancel|sign up|self serve|how fast|how long)\b"),
    ("discovery", r"\b(what software|what tools|best software|alternatives|what kind of tool|how do .+ track)\b"),
    ("trust_results", r"\b(legit|actually work|results|hype|skeptical|safe|gimmick|trustworthy|effective|"
                      r"empty promises|worth it|actually help|users say|hacks|tricks|doesn't increase)\b"),
]
DEFAULT_CATEGORY = "features_fit"


def is_branded(text: str) -> bool:
    return "kasparro" in text.lower()


def categorize(text: str) -> str:
    lowered = text.lower()
    for name, pattern in RULES:
        if re.search(pattern, lowered):
            return name
    return DEFAULT_CATEGORY
