from __future__ import annotations

import io
import re

from app.models.document import DocumentChunk


class UnsupportedDocumentType(ValueError):
    pass


def _heading_level(text: str) -> int | None:
    text = text.strip()
    if re.match(r"^(chapter|part)\s+[\w.-]+", text, re.I):
        return 1
    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S", text):
        level = text.split()[0].rstrip(".)").count(".") + 1
        if level == 1 and len(text) > 80:
            return None
        return level
    return None


def _structured_chunks(document_id: str, version_id: str, blocks: list[str]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    chapter = ""
    section = ""
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        text = "\n".join(body).strip()
        if text:
            chunks.append(DocumentChunk(
                document_id=document_id,
                document_version=version_id,
                index=len(chunks),
                chapter=chapter,
                section=section,
                text=text,
            ))
        body = []

    for block in blocks:
        clean = re.sub(r"\s+", " ", block).strip()
        if not clean:
            continue
        level = _heading_level(clean)
        if level == 1:
            flush()
            chapter, section = clean, ""
        elif level and level >= 2:
            flush()
            section = clean
        else:
            body.append(clean)
    flush()
    return chunks


def parse_document(data: bytes, filename: str, document_id: str, version_id: str) -> list[DocumentChunk]:
    """Parse PDF/DOCX into section-aware chunks, retaining no raw file state."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        blocks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            blocks.extend(text.splitlines())
    elif suffix == "docx":
        from docx import Document

        blocks = [paragraph.text for paragraph in Document(io.BytesIO(data)).paragraphs]
    else:
        raise UnsupportedDocumentType("Only PDF and DOCX documents are supported")

    chunks = _structured_chunks(document_id, version_id, blocks)
    if not chunks:
        raise ValueError("The document contains no extractable text")
    return chunks
