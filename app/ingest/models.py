"""Row models that mirror schemas/input_contract.json.

strict=True: no silent type changes (e.g. "1" is not accepted as order 1).
extra="allow": unknown fields are kept, and the original row is stored unchanged in raw_json anyway.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Engine = Literal["aimode", "chatgpt", "gemini"]
NonEmpty = Field(min_length=1)


class Row(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")


class RunIn(Row):
    run_id: str = NonEmpty


class PromptIn(Row):
    prompt_id: str = NonEmpty
    run_id: str = NonEmpty
    text: str = NonEmpty


class ResponseIn(Row):
    response_id: str = NonEmpty
    run_id: str = NonEmpty
    prompt_id: str = NonEmpty
    engine: Engine
    answer_text: str = NonEmpty
    capture_status: Literal["captured"]
    answer_markdown: str | None = None
    model_version: str | None = None
    provider_timestamp: str | None = None
    archive_stored_at: str | None = None
    settings: dict | None = None


class CitationIn(Row):
    citation_id: str = NonEmpty
    response_id: str = NonEmpty
    prompt_id: str = NonEmpty
    engine: Engine
    order: int = Field(ge=1)
    citation_type: Literal["inline_hyperlink", "sources_panel"]
    url: str = NonEmpty
    domain: str | None = None
    title: str | None = None
    publication_date: str | None = None
