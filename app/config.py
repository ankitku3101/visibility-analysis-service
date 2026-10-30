"""Settings loaded from environment variables (and .env if present)."""
import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

LLMMode = Literal["local", "replay", "stub", "live"]


class Settings(BaseModel):
    db_path: str = "app.db"
    pack_dir: str = "."
    llm_mode: LLMMode = "replay"
    replay_dir: str = "replay"
    analyst_token: str = Field(min_length=1)
    reviewer_token: str = Field(min_length=1)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: float = Field(default=120, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=2)
    llm_max_calls: int = Field(default=450, ge=1)

    @model_validator(mode="after")
    def tokens_must_differ(self):
        # With equal tokens every caller would be "analyst" and nobody could review.
        if self.analyst_token == self.reviewer_token:
            raise ValueError("ANALYST_TOKEN and REVIEWER_TOKEN must be different")
        return self


@lru_cache
def get_settings() -> Settings:
    # load_dotenv never overrides variables that are already set (tests rely on this).
    load_dotenv()
    values = {
        name: os.environ[name.upper()]
        for name in Settings.model_fields
        if name.upper() in os.environ
    }
    return Settings(**values)
