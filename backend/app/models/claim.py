from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ClaimDraft(BaseModel):
    """A claim explicitly expressed by the source."""

    text: str = Field(min_length=1)

    evidence_cited: list[str] = Field(
        default_factory=list
    )

    open_questions: list[str] = Field(
        default_factory=list
    )

    confidence: float = Field(
        default=1.0,
        description="Confidence score between 0.0 and 1.0."
    )

    status: Literal["supported", "unsubstantiated"] = Field(
        default="unsubstantiated",
        description="Argumentative status of the claim."
    )


class Claim(ClaimDraft):
    id: str
    document_id: str
    document_version: str
    chapter: str
    section: str
    source_span: str | None = None
    embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
