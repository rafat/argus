from __future__ import annotations

import logging

from pydantic import TypeAdapter

from app.models.claim import Claim
from app.tools.conflict_analysis import analyze_claim_pairs
from app.tools.conflict_candidates import (
    ClaimPair,
    ConflictCandidateGenerator,
)

logger = logging.getLogger(__name__)


async def analyze_conflicts(
    ctx,
    node_input: dict,
) -> dict:
    """
    Generate semantic retrieval candidates and evaluate them
    using the Conflict Agent.

    ADK workflow boundaries may serialize Pydantic models into
    dictionaries, so claims are explicitly rehydrated here.
    """

    claims = TypeAdapter(list[Claim]).validate_python(
        node_input["claims"]
    )

    top_k = node_input.get(
        "conflict_candidate_top_k",
        5,
    )

    logger.info("--- [ADK Workflow] Generating semantic conflict candidates ---")
    generator = ConflictCandidateGenerator()

    pairs: list[ClaimPair] = generator.generate(
        claims,
        top_k=top_k,
    )
    logger.info(f"--- [ADK Workflow] Found {len(pairs)} candidate claim pairs for contradiction analysis ---")

    logger.info("--- [ADK Workflow] Evaluating claim pairs using Conflict Agent (Gemini) ---")
    conflicts = await analyze_claim_pairs(pairs)
    logger.info(f"--- [ADK Workflow] Contradiction analysis complete. Identified {len(conflicts)} active conflicts ---")

    candidate_pair_info = [
        {
            "claim_a_id": pair.claim_a.id,
            "claim_b_id": pair.claim_b.id,
            "retrieval_distance": pair.retrieval_distance,
        }
        for pair in pairs
    ]

    return {
        "record": node_input["record"],
        "claims": claims,
        "candidate_pairs": candidate_pair_info,
        "conflicts": conflicts,
    }