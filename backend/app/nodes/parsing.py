import logging
from app.models.document import DocumentChunk
from app.tools.document_parser import parse_document

logger = logging.getLogger(__name__)


def parse_upload(ctx) -> dict:
    node_input = ctx.state
    logger.info(f"--- [ADK Workflow] Parsing document: {node_input.get('filename', 'document')} ({node_input.get('content_type', 'unknown')}) ---")
    chunks = parse_document(
        node_input["data"],
        node_input["filename"],
        node_input["document_id"],
        node_input["version_id"],
    )
    logger.info(f"--- [ADK Workflow] Parsing complete. Split into {len(chunks)} chunks ---")
    return {"chunks": chunks, "record": node_input["record"]}
