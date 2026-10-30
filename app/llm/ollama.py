"""Local model through Ollama's /api/chat. Every model answer is saved for replay."""
import httpx

from app.config import Settings
from app.llm.client import LLMError, LLMTimeout
from app.llm.prompts import PROMPT_VERSION
from app.llm.replay import ReplayStore

# num_ctx 8192: the default context is too small for the longest answers and would cut them off.
OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 1024}
# Retries must be able to differ from attempt 1: at temperature 0 the full run hit an Ollama repetition loop
# ("token repeat limit reached") three times in a row (F6). A fixed seed keeps retries reproducible.
RETRY_OPTIONS = {"temperature": 0.3}


def options_for(attempt: int) -> dict:
    return OPTIONS if attempt == 1 else {**OPTIONS, **RETRY_OPTIONS, "seed": attempt}


class OllamaClient:
    mode = "local"

    def __init__(self, settings: Settings, store: ReplayStore | None = None, http: httpx.Client | None = None):
        self.model = settings.ollama_model
        self.base = settings.ollama_url.rstrip("/")
        self.url = self.base + "/api/chat"
        self.http = http or httpx.Client(timeout=settings.llm_timeout_s)
        self.store = store
        if store:
            store.write_meta({"model": self.model, "options": OPTIONS, "retry_options": RETRY_OPTIONS,
                              "prompt_version": PROMPT_VERSION})

    def check(self) -> None:
        """Fail fast before a long run: Ollama must be reachable and the model pulled."""
        try:
            res = self.http.get(self.base + "/api/tags", timeout=5)
            names = {m.get("name") for m in res.json().get("models", [])}
        except (httpx.HTTPError, ValueError, AttributeError):
            raise LLMError("provider_unavailable", f"Ollama is not reachable at {self.base}. Is it running?") from None
        if self.model not in names and f"{self.model}:latest" not in names:
            raise LLMError("model_missing", f"Model {self.model} is not installed. Run: ollama pull {self.model}")

    def _record(self, key: str, attempt: int, kind: str, raw: str | None = None, error_code: str | None = None,
                detail: str | None = None):
        if self.store:
            self.store.record(key, attempt, kind, raw, error_code, detail)

    def complete(self, key: str, messages: list[dict], attempt: int) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False, "format": "json",
                   "options": options_for(attempt)}
        try:
            res = self.http.post(self.url, json=payload)
        except httpx.TimeoutException:
            self._record(key, attempt, "timeout", error_code="timeout")
            raise LLMTimeout() from None
        except httpx.HTTPError as e:
            # Ollama not running is a setup problem, not model behaviour: not saved for replay,
            # so it can never overwrite a good recording.
            raise LLMError("provider_unavailable", str(e)) from None
        if res.status_code != 200:
            # Keep Ollama's own message (e.g. "token repeat limit reached"); F6 was only found by re-sending.
            detail = f"HTTP {res.status_code}: {res.text[:300]}"
            self._record(key, attempt, "error", error_code="provider_error", detail=detail)
            raise LLMError("provider_error", detail)
        try:
            content = res.json()["message"]["content"]
        except (ValueError, KeyError, TypeError):
            detail = f"Unexpected Ollama response: {res.text[:300]}"
            self._record(key, attempt, "error", error_code="provider_error", detail=detail)
            raise LLMError("provider_error", detail) from None
        self._record(key, attempt, "output", raw=content)
        return content
