from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Conflict(BaseModel):
    id: str
    document_id: str
    claim_a_id: str
    claim_b_id: str
    claim_a_text: str
    claim_b_text: str
    explanation: str
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
