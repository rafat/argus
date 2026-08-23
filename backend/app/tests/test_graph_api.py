import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models.claim import Claim
from app.models.conflict import Conflict
from app.models.document import DocumentRecord
from app.tools.argument_graph import ArgumentGraphBuilder

client = TestClient(app)


def test_graph_api_document_not_found():
    """Verify that a 404 is returned if the document does not exist in Firestore."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document_claims.return_value = []
        mock_repo.get_document.return_value = None

        response = client.get("/documents/non-existent-doc/graph")
        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"


def test_graph_api_empty_document_succeeds_but_empty():
    """Verify that an existing document with zero claims returns an empty graph."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document_claims.return_value = []
        mock_repo.get_document.return_value = DocumentRecord(
            id="empty-doc",
            version_id="v-1",
            filename="empty.pdf",
            content_type="application/pdf",
            size_bytes=123,
            status="processed",
        )

        response = client.get("/documents/empty-doc/graph")
        assert response.status_code == 200
        assert response.json() == {"nodes": [], "edges": []}


def test_multiple_disconnected_claims_gets_positions():
    """Test 1: Multiple disconnected claims should all get valid position coordinates."""
    claims = [
        Claim(id="claim-a", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="1", text="Text A"),
        Claim(id="claim-b", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="2", text="Text B"),
        Claim(id="claim-c", document_id="doc-1", document_version="v-1", chapter="Ch 2", section="1", text="Text C"),
    ]
    conflicts = []
    
    builder = ArgumentGraphBuilder()
    graph = builder.build(claims=claims, conflicts=conflicts)
    
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 0
    for node in graph.nodes:
        assert "x" in node.position
        assert "y" in node.position
        assert node.data.conflict_count == 0


def test_multiple_conflicts():
    """Test 2: Multiple conflicts should all be mapped into valid edges."""
    claims = [
        Claim(id="claim-a", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="1", text="Text A"),
        Claim(id="claim-b", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="2", text="Text B"),
        Claim(id="claim-c", document_id="doc-1", document_version="v-1", chapter="Ch 2", section="1", text="Text C"),
    ]
    conflicts = [
        Conflict(
            id="conflict-ab",
            document_id="doc-1",
            claim_a_id="claim-a",
            claim_b_id="claim-b",
            claim_a_text="Text A",
            claim_b_text="Text B",
            explanation="Conflict AB",
            severity="high",
            confidence=0.9
        ),
        Conflict(
            id="conflict-bc",
            document_id="doc-1",
            claim_a_id="claim-b",
            claim_b_id="claim-c",
            claim_a_text="Text B",
            claim_b_text="Text C",
            explanation="Conflict BC",
            severity="medium",
            confidence=0.8
        )
    ]
    
    builder = ArgumentGraphBuilder()
    graph = builder.build(claims=claims, conflicts=conflicts)
    
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2
    
    edge_ids = {edge.id for edge in graph.edges}
    assert edge_ids == {"conflict-ab", "conflict-bc"}
    
    # Check conflict involvement counts
    node_a = next(n for n in graph.nodes if n.id == "claim-a")
    node_b = next(n for n in graph.nodes if n.id == "claim-b")
    node_c = next(n for n in graph.nodes if n.id == "claim-c")
    
    assert node_a.data.conflict_count == 1
    assert node_b.data.conflict_count == 2
    assert node_c.data.conflict_count == 1


def test_centrality_calculation():
    """Test 3: In a line graph A - B - C, node B must have a higher centrality score."""
    claims = [
        Claim(id="claim-a", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="1", text="Text A"),
        Claim(id="claim-b", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="2", text="Text B"),
        Claim(id="claim-c", document_id="doc-1", document_version="v-1", chapter="Ch 2", section="1", text="Text C"),
    ]
    conflicts = [
        Conflict(
            id="conflict-ab",
            document_id="doc-1",
            claim_a_id="claim-a",
            claim_b_id="claim-b",
            claim_a_text="Text A",
            claim_b_text="Text B",
            explanation="Conflict AB",
            severity="high",
            confidence=0.9
        ),
        Conflict(
            id="conflict-bc",
            document_id="doc-1",
            claim_a_id="claim-b",
            claim_b_id="claim-c",
            claim_a_text="Text B",
            claim_b_text="Text C",
            explanation="Conflict BC",
            severity="medium",
            confidence=0.8
        )
    ]
    
    builder = ArgumentGraphBuilder()
    graph = builder.build(claims=claims, conflicts=conflicts)
    
    node_a = next(n for n in graph.nodes if n.id == "claim-a")
    node_b = next(n for n in graph.nodes if n.id == "claim-b")
    node_c = next(n for n in graph.nodes if n.id == "claim-c")
    
    # B has degree 2, A has degree 1, C has degree 1 in degree centrality
    assert node_b.data.centrality > node_a.data.centrality
    assert node_b.data.centrality > node_c.data.centrality


def test_severity_animations():
    """Test 4: High severity conflicts should have animated=True; other severities should have animated=False."""
    claims = [
        Claim(id="claim-a", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="1", text="Text A"),
        Claim(id="claim-b", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="2", text="Text B"),
        Claim(id="claim-c", document_id="doc-1", document_version="v-1", chapter="Ch 2", section="1", text="Text C"),
    ]
    conflicts = [
        Conflict(
            id="conflict-high",
            document_id="doc-1",
            claim_a_id="claim-a",
            claim_b_id="claim-b",
            claim_a_text="Text A",
            claim_b_text="Text B",
            explanation="High severity",
            severity="high",
            confidence=0.9
        ),
        Conflict(
            id="conflict-medium",
            document_id="doc-1",
            claim_a_id="claim-b",
            claim_b_id="claim-c",
            claim_a_text="Text B",
            claim_b_text="Text C",
            explanation="Medium severity",
            severity="medium",
            confidence=0.8
        )
    ]
    
    builder = ArgumentGraphBuilder()
    graph = builder.build(claims=claims, conflicts=conflicts)
    
    edge_high = next(e for e in graph.edges if e.id == "conflict-high")
    edge_medium = next(e for e in graph.edges if e.id == "conflict-medium")
    
    assert edge_high.animated is True
    assert edge_medium.animated is False


def test_malformed_conflict_does_not_crash_graph():
    """Test 5: Conflicts referencing nonexistent claims should be safely ignored and not crash the builder."""
    claims = [
        Claim(id="claim-a", document_id="doc-1", document_version="v-1", chapter="Ch 1", section="1", text="Text A"),
    ]
    conflicts = [
        Conflict(
            id="conflict-malformed",
            document_id="doc-1",
            claim_a_id="claim-a",
            claim_b_id="nonexistent-claim",
            claim_a_text="Text A",
            claim_b_text="Nonexistent",
            explanation="References a nonexistent claim",
            severity="high",
            confidence=0.9
        )
    ]
    
    builder = ArgumentGraphBuilder()
    # This should not raise an exception
    graph = builder.build(claims=claims, conflicts=conflicts)
    
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 0  # Skip the malformed conflict
    assert graph.nodes[0].data.conflict_count == 0
