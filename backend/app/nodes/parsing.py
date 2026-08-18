from app.models.document import DocumentChunk
from app.tools.document_parser import parse_document


def parse_upload(ctx) -> dict:
    node_input = ctx.state
    chunks = parse_document(
        node_input["data"],
        node_input["filename"],
        node_input["document_id"],
        node_input["version_id"],
    )
    return {"chunks": chunks, "record": node_input["record"]}
