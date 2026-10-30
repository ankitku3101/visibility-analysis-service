"""score-v1: points for one successfully analysed response. Pure code, no LLM."""
SCORING_VERSION = "score-v1"

# Out of 100. Recommendation weighs most (the business goal is being suggested, not just named);
# being named comes next; a mention without negative wording rewards accurate, positive representation;
# a kasparro.com citation is a small trust signal.
POINTS = {"mentioned": 30, "recommended": 40, "not_negative": 20, "cited": 10}

METHOD = {
    "version": SCORING_VERSION,
    "scale": "0-100 points per successfully analysed response",
    "points": POINTS,
    "rules": [
        "not_negative is given only when Kasparro is mentioned and not negatively characterised",
        "recommended and negative can only be true when Kasparro is mentioned",
        "group score = average points over succeeded responses only (failed and skipped are not zeros)",
        "score_range = [failed counted as 0, failed counted as 100] over succeeded + failed",
        "low_coverage = fewer than 80% of a group's responses succeeded",
        "branded and unbranded prompts are never combined into one number",
    ],
}


def response_parts(result: dict) -> dict | None:
    """Component values for a succeeded result, or None for failed/skipped."""
    if result.get("status") != "succeeded":
        return None
    mentioned = bool(result.get("mentioned"))
    return {
        "mentioned": mentioned,
        "recommended": mentioned and bool(result.get("recommended")),
        "not_negative": mentioned and not result.get("negative"),
        "cited": bool(result.get("kasparro_cited")),
    }


def response_points(result: dict) -> dict | None:
    parts = response_parts(result)
    if parts is None:
        return None
    points = {name: POINTS[name] if on else 0 for name, on in parts.items()}
    return {"parts": points, "total": sum(points.values())}
