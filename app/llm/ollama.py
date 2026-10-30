"""Local model through Ollama's /api/chat. Every model answer is saved for replay."""
import httpx

from app.config import Settings
from app.llm.client import LLMError, LLMTimeout
from app.llm.prompts import PROMPT_VERSION
from app.llm.replay import ReplayStore

# num_ctx 8192: the default context is too small for the longest answers and would cut them off.
OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 1024}


class OllamaClient:
    mode = "local"

    def __init__(self, settings: Settings, store: ReplayStore | None = None, http: httpx.Client | None = None):
        self.model = settings.ollama_model
        self.url = settings.ollama_url.rstrip("/") + "/api/chat"
        self.http = http or httpx.Client(timeout=settings.llm_timeout_s)
        self.store = store
        if store:
            store.write_meta({"model": self.model, "options": OPTIONS, "prompt_version": PROMPT_VERSION})

    def _record(self, key: str, attempt: int, kind: str, raw: str | None = None, error_code: str | None = None):
        if self.store:
            self.store.record(key, attempt, kind, raw, error_code)

    def complete(self, key: str, messages: list[dict], attempt: int) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False, "format": "json", "options": OPTIONS}
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
            self._record(key, attempt, "error", error_code="provider_error")
            raise LLMError("provider_error", f"Ollama returned HTTP {res.status_code}")
        try:
            content = res.json()["message"]["content"]
        except (ValueError, KeyError, TypeError):
            self._record(key, attempt, "error", error_code="provider_error")
            raise LLMError("provider_error", "Unexpected Ollama response shape") from None
        self._record(key, attempt, "output", raw=content)
        return content
