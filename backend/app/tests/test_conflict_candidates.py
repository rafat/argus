from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.models.claim import Claim
from app.tools.claim_retrieval import RetrievalCandidate
from app.tools.conflict_candidates import (
    ClaimPair,
    ConflictCandidateGenerator,
)


def make_claim(
    claim_id: str,
    text: str,
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


def test_candidate_pairs_are_deduplicated():
    claim_a = make_claim(
        "a",
        "Algorithmic systems increase polarization.",
    )

    claim_b = make_claim(
        "b",
        "Algorithmic systems decrease polarization.",
    )

    retrieval = Mock()

    retrieval.search_similar_claims.side_effect = [
        [
            RetrievalCandidate(
                claim_id="b",
                    distance=0.09,
            )
        ],
        [
            RetrievalCandidate(
                claim_id="a",
                    distance=0.10,
            )
        ],
    ]

    generator = ConflictCandidateGenerator(
        retrieval=retrieval,
    )

    pairs = generator.generate(
        [claim_a, claim_b],
        top_k=5,
    )

    assert len(pairs) == 1

    pair = pairs[0]

    assert pair.key == ("a", "b")


def test_self_matches_are_not_returned():
    claim_a = make_claim(
        "a",
        "Algorithmic systems increase polarization.",
    )

    retrieval = Mock()

    retrieval.search_similar_claims.return_value = []

    generator = ConflictCandidateGenerator(
        retrieval=retrieval,
    )

    pairs = generator.generate(
        [claim_a],
        top_k=5,
    )

    assert pairs == []


def test_external_document_candidates_are_ignored():
    claim_a = make_claim(
        "a",
        "Algorithmic systems increase polarization.",
    )

    retrieval = Mock()

    retrieval.search_similar_claims.return_value = [
        RetrievalCandidate(
            claim_id="external-claim",
            distance=0.95,
            document_id="other-document",
        )
    ]

    generator = ConflictCandidateGenerator(
        retrieval=retrieval,
    )

    pairs = generator.generate(
        [claim_a],
        top_k=5,
    )

    assert pairs == []


def test_local_candidate_generation_with_embeddings():
    claim_a = make_claim(
        "a",
        "Algorithmic systems increase polarization.",
    )
    claim_a.embedding = [1.0, 0.0, 0.0]

    claim_b = make_claim(
        "b",
        "Algorithmic systems decrease polarization.",
    )
    claim_b.embedding = [0.95, 0.05, 0.0]

    claim_c = make_claim(
        "c",
        "Unrelated claim about marine biology.",
    )
    claim_c.embedding = [0.0, 1.0, 0.0]

    generator = ConflictCandidateGenerator()
    pairs = generator.generate(
        [claim_a, claim_b, claim_c],
        top_k=1,
    )

    # Claim A and Claim B are close in vector space, while Claim C is orthogonal
    assert len(pairs) >= 1
    assert any(p.key == ("a", "b") for p in pairs)
    assert not any(p.key == ("a", "c") for p in pairs)


def test_partial_embeddings_combines_local_and_remote():
    # Claim A and Claim B have embeddings
    claim_a = make_claim("a", "High tax rate increases state revenue.")
    claim_a.embedding = [1.0, 0.0]

    claim_b = make_claim("b", "High tax rate decreases state revenue.")
    claim_b.embedding = [0.95, 0.05]

    # Claim C does NOT have an embedding
    claim_c = make_claim("c", "Tax rates affect consumer spending.")
    claim_c.embedding = None

    retrieval = Mock()
    retrieval.search_similar_claims.return_value = [
        RetrievalCandidate(
            claim_id="a",
            distance=0.1,
            document_id="doc-1",
        )
    ]

    generator = ConflictCandidateGenerator(retrieval=retrieval)
    pairs = generator.generate([claim_a, claim_b, claim_c], top_k=2)

    # (a, b) generated locally via embeddings
    # (a, c) generated remotely via retrieval for claim_c
    keys = {p.key for p in pairs}
    assert ("a", "b") in keys
    assert ("a", "c") in keys
    assert len(pairs) == 2


def test_min_score_filters_weak_candidates():
    claim_a = make_claim("a", "Claim A text")
    claim_a.embedding = [1.0, 0.0]

    claim_b = make_claim("b", "Weakly related claim B")
    claim_b.embedding = [0.3, 0.95]  # Cosine similarity around 0.3

    generator = ConflictCandidateGenerator(default_min_score=0.5)

    # With default threshold 0.5, weak similarity (0.3) should be filtered out
    pairs = generator.generate([claim_a, claim_b], top_k=5)
    assert len(pairs) == 0

    # With custom lower threshold (0.2), pair should be included
    pairs_low = generator.generate([claim_a, claim_b], top_k=5, min_score=0.2)
    assert len(pairs_low) == 1
    assert pairs_low[0].key == ("a", "b")


def test_empty_and_zero_top_k():
    generator = ConflictCandidateGenerator()
    assert generator.generate([]) == []

    claim = make_claim("a", "Some text")
    claim.embedding = [1.0, 0.0]
    assert generator.generate([claim], top_k=0) == []


def test_claim_pair_accepts_legacy_retrieval_distance_keyword():
    pair = ClaimPair(
        claim_a=make_claim("a", "Claim A"),
        claim_b=make_claim("b", "Claim B"),
        retrieval_distance=0.9,
    )

    assert pair.retrieval_score == 0.9
    assert pair.retrieval_distance == 0.9


def test_remote_candidates_apply_min_score():
    claim_a = make_claim("a", "Claim A")
    claim_b = make_claim("b", "Claim B")

    retrieval = Mock()
    retrieval.search_similar_claims.return_value = [
        RetrievalCandidate(claim_id="b", distance=0.9),
    ]

    generator = ConflictCandidateGenerator(retrieval=retrieval)

    assert generator.generate_remote(
        [claim_a],
        all_doc_claims=[claim_a, claim_b],
        min_score=0.5,
    ) == []

    pairs = generator.generate_remote(
        [claim_a],
        all_doc_claims=[claim_a, claim_b],
        min_score=0.05,
    )
    assert len(pairs) == 1
    assert pairs[0].retrieval_score == pytest.approx(0.1)


def test_remote_fallback_is_used_for_partial_embeddings():
    claim_a = make_claim("a", "Claim A")
    claim_b = make_claim("b", "Claim B")
    claim_a.embedding = [1.0, 0.0]

    retrieval = Mock()
    retrieval.search_similar_claims.return_value = [
        RetrievalCandidate(claim_id="a", distance=0.1),
    ]

    generator = ConflictCandidateGenerator(retrieval=retrieval)
    pairs = generator.generate(
        [claim_a, claim_b],
        top_k=5,
        min_score=0.5,
    )

    assert {pair.key for pair in pairs} == {("a", "b")}
