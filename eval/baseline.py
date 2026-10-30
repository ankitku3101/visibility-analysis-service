"""Rule-based baseline: keywords only, no LLM. Same output shape as the LLM path so both are graded alike."""
import re

from app.analysis.preprocess import MENTION, find_mention, kasparro_cited, strip_url_list

RECOMMEND = re.compile(r"recommend|good fit|designed specifically|best choice|worth it|great option|suitable|"
                       r"makes sense|well suited|strong option", re.IGNORECASE)
NEGATIVE = re.compile(r"not (a )?widely|not well[- ]known|unknown|no (specific|public|verified)|limited|lack|"
                      r"not recognized|unclear|harder to justify|scam|avoid|concern", re.IGNORECASE)
# Fixed list of AI-visibility tools (a baseline cannot discover new names).
KNOWN_TOOLS = ["Profound", "Peec AI", "Otterly", "AthenaHQ", "Semrush", "Ahrefs", "Conductor", "ZipTie",
               "Scrunch", "HubSpot", "Rank Math", "Dageno", "Goodie", "Quattr", "Forzeo", "Topify", "AI-Netra"]
SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def classify(question: str, answer_text: str, citations: list[dict]) -> dict:
    cleaned = strip_url_list(answer_text)
    mentioned, _ = find_mention(cleaned)
    kasparro_sentences = [s for s in SENTENCES.split(cleaned) if MENTION.search(s)]
    return {
        "status": "succeeded",
        "mentioned": mentioned,
        "recommended": mentioned and any(RECOMMEND.search(s) for s in kasparro_sentences),
        "negative": mentioned and any(NEGATIVE.search(s) for s in kasparro_sentences),
        "competitors": [t for t in KNOWN_TOOLS if re.search(rf"\b{re.escape(t)}", cleaned, re.IGNORECASE)],
        "position": None,
        "kasparro_cited": kasparro_cited(citations),
    }
