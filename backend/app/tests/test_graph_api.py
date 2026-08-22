import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models.claim import Claim
from app.models.conflict import Conflict
from app.models.document import DocumentRecord

client = TestClient(app)


def test_graph_api_document_not_found():
    """Verify that a 404 is returned if the document does not exist in Firestore."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_claims.return_value = []
        mock_repo.get_document.return_value = None

        response = client.get("/documents/non-existent-doc/graph")
        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"


def test_graph_api_empty_document_succeeds_but_empty():
    """Verify that an existing document with zero claims returns an empty graph."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_claims.return_value = []
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


def test_graph_api_generates_valid_react_flow_json():
    """Verify that claims and conflicts are parsed into a valid React Flow graph format."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        
        mock_repo.get_claims.return_value = [
            Claim(
                id="claim-1",
                document_id="doc-123",
                document_version="v-1",
                chapter="Chapter 1",
                section="1.1",
                text="Algorithmic recommendation engines systematically increase polarization.",
                confidence=0.9,
                status="unsubstantiated",
            ),
            Claim(
                id="claim-2",
                document_id="doc-123",
                document_version="v-1",
                chapter="Chapter 1",
                section="1.2",
                text="Recommendation systems decrease polarization by displaying diverse content.",
                confidence=0.85,
                status="supported",
            ),
        ]
        
        mock_repo.get_conflicts.return_value = [
            Conflict(
                id="conflict-1",
                document_id="doc-123",
                claim_a_id="claim-1",
                claim_b_id="claim-2",
                claim_a_text="Algorithmic recommendation engines systematically increase polarization.",
                claim_b_text="Recommendation systems decrease polarization by displaying diverse content.",
                explanation="Semantic contradiction regarding the effect on political polarization.",
                severity="high",
                confidence=0.95,
            )
        ]

        response = client.get("/documents/doc-123/graph")
        assert response.status_code == 200
        
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        
        nodes = data["nodes"]
        edges = data["edges"]
        
        assert len(nodes) == 2
        assert len(edges) == 1
        
        # Verify node structure for React Flow
        node_1 = next(n for n in nodes if n["id"] == "claim-1")
        assert node_1["type"] == "claimNode"
        assert "position" in node_1
        assert "x" in node_1["position"]
        assert "y" in node_1["position"]
        assert node_1["data"]["text"] == "Algorithmic recommendation engines systematically increase polarization."
        assert node_1["data"]["status"] == "unsubstantiated"
        assert node_1["data"]["confidence"] == 0.9
        assert "centrality" in node_1["data"]
        
        # Verify edge structure
        edge = edges[0]
        assert edge["id"] == "conflict-1"
        assert edge["source"] == "claim-1"
        assert edge["target"] == "claim-2"
        assert edge["type"] == "conflictEdge"
        assert edge["animated"] is True
        assert edge["data"]["severity"] == "high"
        assert edge["data"]["confidence"] == 0.95
