from __future__ import annotations

from unittest.mock import Mock

from app.models.claim import Claim
from app.tools.claim_retrieval import RetrievalCandidate
from app.tools.conflict_candidates import (
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
                distance=0.91,
            )
        ],
        [
            RetrievalCandidate(
                claim_id="a",
                distance=0.90,
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