"""Saved LLM outputs: written by local runs, played back in replay mode.

Files: <REPLAY_DIR>/<PROMPT_VERSION>/<key>.json = list of attempts, plus meta.json with the model settings.
Replay returns the entry for the same attempt number, so failures replay exactly like successes.
"""
import hashlib
import json
import os
import re
from pathlib import Path

from app.llm.client import LLMError, LLMTimeout
from app.llm.prompts import PROMPT_VERSION

SAFE_KEY = re.compile(r"[A-Za-z0-9_.-]{1,128}")
# Windows device names cannot be used as file names on some Windows versions.
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class ReplayStore:
    def __init__(self, root: str, version: str = PROMPT_VERSION):
        self.dir = Path(root) / version

    def path(self, key: str) -> Path:
        # Keys come from imported data, so never trust them as file names.
        if SAFE_KEY.fullmatch(key) and key not in (".", "..", "meta") and key.split(".")[0].lower() not in RESERVED:
            name = key
        else:
            name = "key-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.dir / f"{name}.json"

    def _write(self, path: Path, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash never leaves half a file

    def load(self, key: str) -> list[dict]:
        path = self.path(key)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        return data if isinstance(data, list) else []

    def record(self, key: str, attempt: int, kind: str, raw: str | None = None, error_code: str | None = None):
        # Attempt 1 starts a fresh list, so a new local run replaces the old recording.
        entries = [] if attempt == 1 else self.load(key)[: attempt - 1]
        entries.append({"attempt": attempt, "kind": kind, "raw": raw, "error_code": error_code})
        self._write(self.path(key), entries)

    def write_meta(self, meta: dict) -> None:
        self._write(self.dir / "meta.json", meta)

    def read_meta(self) -> dict:
        try:
            return json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


class ReplayClient:
    mode = "replay"

    def __init__(self, store: ReplayStore):
        self.store = store
        self.model = store.read_meta().get("model")  # the model that made the recording

    def complete(self, key: str, messages: list[dict], attempt: int) -> str:
        entries = self.store.load(key)
        if attempt > len(entries):
            raise LLMError("replay_missing", f"No saved attempt {attempt} for {key}")
        entry = entries[attempt - 1]
        if entry.get("kind") == "timeout":
            raise LLMTimeout()
        if entry.get("kind") == "error":
            raise LLMError(entry.get("error_code") or "provider_error")
        return entry.get("raw") or ""
