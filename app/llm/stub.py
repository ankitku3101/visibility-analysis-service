"""Deterministic fake LLM for tests. Not a model-quality signal."""
import json

from app.llm.client import LLMError, LLMTimeout

DEFAULT_OUTPUT = json.dumps({
    "recommended": False, "recommended_quote": None,
    "negative": False, "negative_quote": None,
    "competitors": [], "ranked_list": None,
})


class StubClient:
    """script = {key: ["timeout", "timeout", "ok"]}; the step is picked by attempt number.
    Steps: ok, ok:<json>, timeout, malformed, empty, error. Missing key or step → ok."""
    mode = "stub"
    model = "stub"

    def __init__(self, script: dict[str, list[str]] | None = None):
        self.script = script or {}

    def complete(self, key: str, messages: list[dict], attempt: int) -> str:
        steps = self.script.get(key, [])
        step = steps[attempt - 1] if attempt <= len(steps) else "ok"
        if step == "ok":
            return DEFAULT_OUTPUT
        if step.startswith("ok:"):
            return step[3:]
        if step == "timeout":
            raise LLMTimeout()
        if step == "malformed":
            return "not json {"
        if step == "empty":
            return ""
        if step == "error":
            raise LLMError("provider_error")
        raise ValueError(f"Unknown stub step: {step}")
