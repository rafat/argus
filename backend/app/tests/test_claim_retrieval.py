from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.models.claim import Claim
from app.tools.claim_retrieval import (
    AgentRetrievalClaimIndex,
    RetrievalCandidate,
)


def make_claim(
    claim_id: str = "claim-1",
    text: str = "Algorithmic systems influence political polarization.",
) -> Claim:
    return Claim(
        id=claim_id,
        document_id="doc-1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.1",
        text=text,
        evidence_cited=[],
        confidence=0.9,
        status="supported",
        open_questions=[],
    )


class FakeEmbeddingService:
    dimensions = 3072

    def embed_claim(self, claim):
        return [0.1] * self.dimensions

    def embed_query(self, query):
        return [0.2] * self.dimensions


def test_collection_name():
    client = Mock()

    index = AgentRetrievalClaimIndex(
        client=client,
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    assert (
        index.collection_name
        == "projects/argus-505505/"
        "locations/us-central1/"
        "collections/argusclaims"
    )


def test_data_projection():
    index = AgentRetrievalClaimIndex(
        client=Mock(),
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    claim = make_claim()

    data = index._data_for_claim(claim)

    assert data == {
        "claim_id": "claim-1",
        "document_id": "doc-1",
        "document_version": "v1",
        "text": "Algorithmic systems influence political polarization.",
        "chapter": "Chapter 1",
        "section": "1.1",
        "status": "supported",
        "confidence": 0.9,
    }


def test_search_rejects_invalid_top_k():
    index = AgentRetrievalClaimIndex(
        client=Mock(),
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    with pytest.raises(ValueError):
        index.search("test", top_k=0)


def test_upsert_claim_uses_3072_dimension_embedding():
    client = Mock()

    index = AgentRetrievalClaimIndex(
        client=client,
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    claim = make_claim()

    index.upsert_claim(claim)

    client.create_data_object.assert_called_once()

    request = client.create_data_object.call_args.kwargs["request"]

    assert request.parent == index.collection_name
    assert request.data_object_id == claim.id

    vector = request.data_object.vectors["claim_embedding"]

    assert len(vector.dense.values) == 3072


def test_search_returns_retrieval_candidates():
    search_client = Mock()

    result_1 = Mock()
    result_1.data_object.data_object_id = "claim-2"
    result_1.data_object.data = {
        "claim_id": "claim-2",
        "document_id": "doc-1",
        "document_version": "v1",
        "text": "Algorithmic systems affect polarization.",
    }
    result_1.distance = 0.87

    result_2 = Mock()
    result_2.data_object.data_object_id = "claim-3"
    result_2.data_object.data = {
        "claim_id": "claim-3",
        "document_id": "doc-1",
        "document_version": "v1",
        "text": "Social media influences political behavior.",
    }
    result_2.distance = 0.72

    response = Mock()
    response.results = [
        result_1,
        result_2,
    ]

    search_client.search_data_objects.return_value = response

    index = AgentRetrievalClaimIndex(
        client=Mock(),
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    index.search_client = search_client

    results = index.search(
        "Algorithmic polarization",
        top_k=5,
    )

    assert len(results) == 2

    assert results[0].claim_id == "claim-2"
    assert results[0].distance == 0.87
    assert results[0].document_id == "doc-1"
    assert results[0].document_version == "v1"
    assert results[0].text == "Algorithmic systems affect polarization."

    assert results[1].claim_id == "claim-3"
    assert results[1].distance == 0.72


def test_search_similar_claims_removes_self():
    search_client = Mock()

    result_self = Mock()
    result_self.data_object.data_object_id = "claim-1"
    result_self.data_object.data = {
        "claim_id": "claim-1",
        "document_id": "doc-1",
        "document_version": "v1",
        "text": "Algorithmic systems influence political polarization.",
    }
    result_self.distance = 1.0

    result_other = Mock()
    result_other.data_object.data_object_id = "claim-2"
    result_other.data_object.data = {
        "claim_id": "claim-2",
        "document_id": "doc-1",
        "document_version": "v1",
        "text": "Algorithmic systems decrease political polarization.",
    }
    result_other.distance = 0.8

    response = Mock()
    response.results = [
        result_self,
        result_other,
    ]

    search_client.search_data_objects.return_value = response

    index = AgentRetrievalClaimIndex(
        client=Mock(),
        embedding_service=FakeEmbeddingService(),
        project_id="argus-505505",
        location="us-central1",
        collection_id="argusclaims",
    )

    index.search_client = search_client

    results = index.search_similar_claims(
        make_claim("claim-1"),
        top_k=5,
    )

    assert len(results) == 1
    assert results[0].claim_id == "claim-2"
    assert results[0].distance == 0.8


@pytest.mark.integration
def test_agent_retrieval_existing_test_object():
    import os

    from dotenv import load_dotenv

    load_dotenv()

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        pytest.skip("GOOGLE_CLOUD_PROJECT not configured")

    index = AgentRetrievalClaimIndex()

    results = index.search(
        (
            "Algorithmic recommendation systems systematically increase "
            "political polarization by amplifying emotionally charged content."
        ),
        top_k=5,
    )

    assert len(results) >= 1
    assert results[0].claim_id == "argus-test-claim-001"