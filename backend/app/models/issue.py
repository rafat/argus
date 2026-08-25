from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field


class Issue(BaseModel):
    id: str
    document_id: str
    version_id: str
    claim_id: str | None = None
    section: str = ""
    issue_type: str  # e.g., "evidence", "logic", "socratic"
    description: str
    question_text: str = ""
    question_type: str  # e.g., "evidence", "logic", "socratic"
    status: Literal["open", "addressed", "persistent", "escalated"] = "open"
    first_detected_version: str
    last_checked_version: str
    escalation_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IssueEvent(BaseModel):
    id: str
    issue_id: str
    version_id: str
    previous_status: str | None = None
    new_status: str
    event_type: str  # e.g., "created", "re_analyzed", "escalated", "ignored"
    explanation: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

