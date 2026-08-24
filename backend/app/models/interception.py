from datetime import datetime
from pydantic import BaseModel, Field


class InterceptionRecord(BaseModel):
    id: str
    document_id: str
    user_prompt: str
    classification_reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
