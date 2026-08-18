from types import SimpleNamespace

from app.models.claim import ClaimDraft
from app.models.document import DocumentChunk
from app.tools.document_parser import _structured_chunks
from app.workflows.document_workflow import build_chunk_workflow, build_document_workflow


class FakeExtractionAgent:
    def extract(self, chunk, correction=None):
        return [ClaimDraft(
            text=f"The argument in {chunk.section or chunk.chapter} is testable.",
            evidence_cited=["citation-1"],
            confidence=0.9,
            status="supported",
            open_questions=[],
        )]


def test_parser_preserves_chapter_and_section():
    chunks = _structured_chunks("doc", "v1", ["Chapter 1 Introduction", "1.1 Scope", "The claim.", "1.2 Method", "The method."])
    assert [(c.chapter, c.section, c.text) for c in chunks] == [
        ("Chapter 1 Introduction", "1.1 Scope", "The claim."),
        ("Chapter 1 Introduction", "1.2 Method", "The method."),
    ]


def test_adk_workflows_build_graphs():
    chunk_workflow = build_chunk_workflow()
    document_workflow = build_document_workflow(repository=object())
    assert chunk_workflow.name == "chunk_extraction_workflow"
    assert document_workflow.name == "document_workflow"
    assert "extraction_agent" in {node.name for node in chunk_workflow.graph.nodes}
    assert [node.name for node in document_workflow.graph.nodes] == [
        "__START__", "parse_document", "extract_chunks", "persist_claims"
    ]


def test_extraction_node_has_bounded_retry():
    workflow = build_chunk_workflow()
    extraction = next(node for node in workflow.graph.nodes if node.name == "extraction_agent")
    assert extraction.retry_config.max_attempts == 3
