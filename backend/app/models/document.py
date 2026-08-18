from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    document_id: str
    document_version: str
    index: int
    chapter: str = ""
    section: str = ""
    text: str = Field(min_length=1)
    source_span: str | None = None


class DocumentRecord(BaseModel):
    id: str
    version_id: str
    filename: str
    content_type: str
    size_bytes: int
    storage_uri: str | None = None
    status: Literal["uploaded", "processing", "processed", "failed"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
