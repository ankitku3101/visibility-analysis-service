"""Report content and request bodies. extra="forbid" everywhere: unknown fields (e.g. "scores" or "actor"
in a PATCH) are rejected with 422 instead of being silently ignored."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(max_length=200)]
Text = Annotated[str, StringConstraints(max_length=4000)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Strict):
    response_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Diagnostic(Strict):
    id: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    title: Title
    pattern: Text = ""          # what the answers show (observation)
    explanation: Text = ""      # possible reason (hypothesis)
    test_evidence: Text = ""    # what evidence would confirm or reject the explanation
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=10)


class Remedy(Strict):
    id: Annotated[str, StringConstraints(min_length=1, max_length=20)]
    priority: int = Field(ge=1, le=3)
    title: Title
    problem: Text = ""
    diagnostic_ids: list[str] = Field(default_factory=list, max_length=3)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=10)
    action: Text = ""
    expected_benefit: Text = ""
    effort: Literal["low", "medium", "high"]
    uncertainty: Text = ""
    validation_step: Text = ""


class ReportContent(Strict):
    scores: dict
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=10)
    remedies: list[Remedy] = Field(default_factory=list, max_length=10)
    notes: Text = ""


class CreateReport(Strict):
    analysis_id: int = Field(ge=1)


class PatchBody(Strict):
    """Fields that are sent replace the whole list/value. `scores` is computed and cannot be sent."""
    diagnostics: list[Diagnostic] | None = Field(default=None, max_length=10)
    remedies: list[Remedy] | None = Field(default=None, max_length=10)
    notes: Text | None = None

    @field_validator("diagnostics", "remedies", "notes")
    @classmethod
    def not_null(cls, value):
        # None only means "not sent". An explicit null would reach the content model and fail there as a 500.
        if value is None:
            raise ValueError("cannot be null; leave the field out to keep it unchanged")
        return value


class DecisionBody(Strict):
    version: int = Field(ge=1, description="The submitted version being decided; must be the latest")
    decision: Literal["approve", "reject"]
    comment: Comment
