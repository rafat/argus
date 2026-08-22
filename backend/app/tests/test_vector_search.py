from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from app.models.claim import Claim
from app.tools.vector_search import (
    EmbeddingService,
    LocalClaimVectorIndex,
    SimilarClaim,
    VectorSearchService,
    cosine_similarity,
)


# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------

load_dotenv()


def _integration_environment_available() -> bool:
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


# ---------------------------------------------------------------------------
# Unit tests — no Google Cloud required
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical_vectors():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]

    assert cosine_similarity(v1, v2) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0]

    assert cosine_similarity(v1, v2) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    v1 = [1.0, 0.0, 0.0]
    v2 = [-1.0, 0.0, 0.0]

    assert cosine_similarity(v1, v2) == pytest.approx(-1.0)


def test_cosine_similarity_empty_vectors():
    assert cosine_similarity([], []) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    v1 = [0.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]

    assert cosine_similarity(v1, v2) == pytest.approx(0.0)


def test_cosine_similarity_dimension_mismatch():
    v1 = [1.0, 0.0]
    v2 = [1.0, 0.0, 0.0]

    with pytest.raises(ValueError, match="dimensions do not match"):
        cosine_similarity(v1, v2)


# ---------------------------------------------------------------------------
# Local vector index tests — no Google Cloud required
# ---------------------------------------------------------------------------

def make_claim(
    claim_id: str,
    text: str,
    embedding: list[float],
) -> Claim:
    return Claim(
        id=claim_id,
        document_id="doc-1",
        document_version="version-1",
        chapter="Chapter 1",
        section="1.1",
        text=text,
        embedding=embedding,
    )


def test_local_index_add_and_search():
    index = LocalClaimVectorIndex()

    claim_a = make_claim(
        "a",
        "Algorithmic recommendation systems increase political polarization.",
        [1.0, 0.0, 0.0],
    )

    claim_b = make_claim(
        "b",
        "Recommendation algorithms contribute to ideological polarization.",
        [0.95, 0.05, 0.0],
    )

    claim_c = make_claim(
        "c",
        "Bananas contain potassium.",
        [0.0, 1.0, 0.0],
    )

    index.add_many([claim_a, claim_b, claim_c])

    assert index.size == 3

    results = index.search_claim(
        claim_a,
        top_k=2,
        min_score=0.5,
    )

    assert len(results) == 1
    assert isinstance(results[0], SimilarClaim)
    assert results[0].claim.id == "b"
    assert results[0].score > 0.5


def test_local_index_excludes_target_claim():
    index = LocalClaimVectorIndex()

    claim_a = make_claim(
        "a",
        "Algorithmic recommendation systems increase political polarization.",
        [1.0, 0.0, 0.0],
    )

    index.add(claim_a)

    results = index.search_claim(
        claim_a,
        top_k=5,
        min_score=0.0,
    )

    assert results == []


def test_local_index_respects_top_k():
    index = LocalClaimVectorIndex()

    target = make_claim(
        "target",
        "Target claim",
        [1.0, 0.0, 0.0],
    )

    claim_b = make_claim(
        "b",
        "Similar claim B",
        [0.99, 0.01, 0.0],
    )

    claim_c = make_claim(
        "c",
        "Similar claim C",
        [0.98, 0.02, 0.0],
    )

    claim_d = make_claim(
        "d",
        "Similar claim D",
        [0.97, 0.03, 0.0],
    )

    index.add_many(
        [
            target,
            claim_b,
            claim_c,
            claim_d,
        ]
    )

    results = index.search_claim(
        target,
        top_k=2,
        min_score=0.5,
    )

    assert len(results) == 2
    assert results[0].claim.id == "b"
    assert results[1].claim.id == "c"


def test_local_index_respects_min_score():
    index = LocalClaimVectorIndex()

    target = make_claim(
        "target",
        "Target claim",
        [1.0, 0.0, 0.0],
    )

    similar = make_claim(
        "similar",
        "Similar claim",
        [0.9, 0.1, 0.0],
    )

    unrelated = make_claim(
        "unrelated",
        "Unrelated claim",
        [0.0, 1.0, 0.0],
    )

    index.add_many(
        [
            target,
            similar,
            unrelated,
        ]
    )

    results = index.search_claim(
        target,
        top_k=5,
        min_score=0.8,
    )

    assert len(results) == 1
    assert results[0].claim.id == "similar"


def test_local_index_rejects_claim_without_embedding():
    index = LocalClaimVectorIndex()

    claim = Claim(
        id="a",
        document_id="doc-1",
        document_version="version-1",
        chapter="Chapter 1",
        section="1.1",
        text="Claim without an embedding.",
    )

    with pytest.raises(ValueError, match="does not contain an embedding"):
        index.add(claim)


# ---------------------------------------------------------------------------
# Embedding service integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_embedding_service_generates_embedding():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = EmbeddingService()

    embedding = service.embed(
        "Algorithmic recommendation systems can influence political polarization."
    )

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(value, float) for value in embedding)


@pytest.mark.integration
def test_embedding_service_rejects_empty_text():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = EmbeddingService()

    with pytest.raises(ValueError, match="empty text"):
        service.embed("")


# ---------------------------------------------------------------------------
# VectorSearchService integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_vector_search_service_embedding():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = VectorSearchService()

    embedding = service.get_embedding(
        "Test claim text for embedding generation."
    )

    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(value, float) for value in embedding)


@pytest.mark.integration
def test_vector_search_service_claim_embedding():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = VectorSearchService()

    claim = Claim(
        id="a",
        document_id="doc-1",
        document_version="version-1",
        chapter="Chapter 1",
        section="1.1",
        text=(
            "Algorithmic recommendation systems increase "
            "political polarization."
        ),
    )

    embedding = service.embed_claim(claim)

    assert isinstance(embedding, list)
    assert len(embedding) > 0


# ---------------------------------------------------------------------------
# End-to-end semantic retrieval test
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_query_similar_claims():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = VectorSearchService()

    # -----------------------------------------------------------------------
    # Target claim
    # -----------------------------------------------------------------------

    claim_a = Claim(
        id="a",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.1",
        text=(
            "Engagement-driven recommendation algorithms "
            "increase political polarization."
        ),
    )

    # -----------------------------------------------------------------------
    # Semantically similar claim
    # -----------------------------------------------------------------------

    claim_b = Claim(
        id="b",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.2",
        text=(
            "Algorithmic recommendation systems contribute "
            "to greater ideological polarization."
        ),
    )

    # -----------------------------------------------------------------------
    # Related but different claim
    # -----------------------------------------------------------------------

    claim_c = Claim(
        id="c",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.3",
        text=(
            "Political polarization is also influenced by "
            "economic inequality and demographic sorting."
        ),
    )

    # -----------------------------------------------------------------------
    # Completely unrelated claim
    # -----------------------------------------------------------------------

    claim_d = Claim(
        id="d",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.4",
        text=(
            "The quick brown fox jumps over the lazy dog."
        ),
    )

    # Generate embeddings.
    service.index_claims(
        [
            claim_a,
            claim_b,
            claim_c,
            claim_d,
        ]
    )

    # Retrieve nearest neighbors.
    results = service.query_similar_claims(
        claim_a,
        limit=3,
        min_score=0.0,
    )

    # The target itself must never be returned.
    returned_ids = [claim.id for claim, _ in results]

    assert "a" not in returned_ids

    # We should have retrieved candidates.
    assert len(results) > 0

    # The algorithmic-polarization claim should be among the
    # strongest candidates.
    assert "b" in returned_ids

    # The completely unrelated claim should not be the top result.
    assert results[0][0].id == "b"

    # Scores should be floating-point similarity values.
    for claim, score in results:
        assert isinstance(claim, Claim)
        assert isinstance(score, float)

    # Results must be sorted from highest to lowest similarity.
    scores = [score for _, score in results]

    assert scores == sorted(
        scores,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Compatibility test for the original candidate-list API
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_query_similar_claims_with_explicit_candidates():
    if not _integration_environment_available():
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    service = VectorSearchService()

    claim_a = Claim(
        id="a",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.1",
        text=(
            "Engagement-driven recommendation algorithms "
            "increase political polarization."
        ),
    )

    claim_b = Claim(
        id="b",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.2",
        text=(
            "Algorithmic recommendation systems contribute "
            "to greater ideological polarization."
        ),
    )

    claim_c = Claim(
        id="c",
        document_id="doc1",
        document_version="v1",
        chapter="Chapter 1",
        section="1.3",
        text="Bananas contain potassium.",
    )

    claim_a.embedding = service.embed_claim(claim_a)
    claim_b.embedding = service.embed_claim(claim_b)
    claim_c.embedding = service.embed_claim(claim_c)

    results = service.query_similar_claims(
        claim_a,
        [claim_b, claim_c],
        limit=2,
        min_score=0.0,
    )

    assert len(results) == 2

    assert results[0][0].id == "b"

    assert all(
        isinstance(score, float)
        for _, score in results
    )