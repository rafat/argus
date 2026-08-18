from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ClaimDraft(BaseModel):
    """The model-facing portion of a claim."""

    text: str = Field(min_length=1)
    evidence_cited: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    status: Literal["supported", "unsubstantiated"]
    open_questions: list[str] = Field(default_factory=list)


class Claim(ClaimDraft):
    id: str
    document_id: str
    document_version: str
    chapter: str
    section: str
    source_span: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
