"""LLM client interface and the bounded retry loop shared by every mode."""
import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.llm.prompts import ClassifyOutput

MAX_OUTPUT_CHARS = 8000
NO_RETRY = {"replay_missing"}  # retrying cannot change these


class LLMTimeout(Exception):
    pass


class LLMError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class EvidenceError(Exception):
    """Raised by a `validate` callback when a quote is not found in the answer."""


class OutputError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class LLMClient(Protocol):
    mode: str
    model: str | None

    def complete(self, key: str, messages: list[dict], attempt: int) -> str:
        """Return the raw model text. `key` is a response_id or eval case_id; `attempt` starts at 1."""


@dataclass
class Budget:
    """Caps the total number of LLM calls in one run."""
    limit: int
    used: int = 0


@dataclass
class Outcome:
    status: str  # "succeeded" | "failed"
    data: ClassifyOutput | None
    error_code: str | None
    attempts: int


LogFn = Callable[..., None]  # log(attempt=, status=, latency_ms=, error_code=)


def parse_output(raw: str | None) -> ClassifyOutput:
    if raw is None or not raw.strip():
        raise OutputError("empty_output")
    if len(raw) > MAX_OUTPUT_CHARS:
        raise OutputError("malformed_output")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        raise OutputError("malformed_output") from None
    if not isinstance(obj, dict):
        raise OutputError("malformed_output")
    try:
        return ClassifyOutput.model_validate(obj)
    except ValidationError:
        raise OutputError("malformed_output") from None


def call_with_retries(client: LLMClient, key: str, messages: list[dict], settings: Settings, budget: Budget,
                      validate: Callable[[ClassifyOutput], None] | None = None,
                      log: LogFn | None = None) -> Outcome:
    max_attempts = settings.llm_max_retries + 1
    last_error = None
    attempt = 0
    while attempt < max_attempts:
        if budget.used >= budget.limit:
            return Outcome("failed", None, "call_limit_reached", attempt)
        attempt += 1
        budget.used += 1
        started = time.perf_counter()
        data, error = None, None
        try:
            data = parse_output(client.complete(key, messages, attempt))
            if validate:
                validate(data)
        except LLMTimeout:
            error = "timeout"
        except (LLMError, OutputError) as e:
            error = e.code
        except EvidenceError:
            error = "evidence_not_found"
        latency_ms = int((time.perf_counter() - started) * 1000)
        if log:
            log(attempt=attempt, status="ok" if error is None else "error", latency_ms=latency_ms, error_code=error)
        if error is None:
            return Outcome("succeeded", data, None, attempt)
        last_error = error
        if error in NO_RETRY:
            break
    return Outcome("failed", None, last_error, attempt)


def get_client(settings: Settings) -> LLMClient:
    # Imported here so each backend module stays independent of this one.
    from app.llm.ollama import OllamaClient
    from app.llm.replay import ReplayClient, ReplayStore
    from app.llm.stub import StubClient

    if settings.llm_mode == "local":
        return OllamaClient(settings, store=ReplayStore(settings.replay_dir))
    if settings.llm_mode == "replay":
        return ReplayClient(ReplayStore(settings.replay_dir))
    if settings.llm_mode == "stub":
        return StubClient()
    raise AppError(400, "live_not_configured", "LLM_MODE=live needs hosted model access, which was not provided.")
