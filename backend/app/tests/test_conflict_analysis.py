from __future__ import annotations

import pytest

from app.models.claim import Claim
from app.tools.conflict_analysis import evaluate_claim_pair
from app.tools.conflict_candidates import ClaimPair


def make_claim(
    claim_id: str,
    text: str,
) -> Claim:
    return Claim(
        id=claim_id,
        document_id="doc-test",
        document_version="v1",
        chapter="Test Chapter",
        section="Test Section",
        text=text,
        evidence_cited=[],
        confidence=0.9,
        status="supported",
        open_questions=[],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflict_analysis_detects_real_contradiction():
    claim_a = make_claim(
        "a",
        "Algorithmic curation systematically increases "
        "political polarization and erodes democratic norms.",
    )

    claim_b = make_claim(
        "b",
        "Algorithmic recommendation engines systematically "
        "decrease political polarization and improve democratic norms.",
    )

    pair = ClaimPair(
        claim_a=claim_a,
        claim_b=claim_b,
        retrieval_distance=0.9,
    )

    resolution = await evaluate_claim_pair(pair)

    assert resolution.is_conflict is True
    assert resolution.severity in (
        "low",
        "medium",
        "high",
    )
    assert resolution.explanation
    assert 0.0 <= resolution.confidence <= 1.0