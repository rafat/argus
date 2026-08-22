from __future__ import annotations

from app.models.claim import Claim
from app.tools.claim_retrieval import AgentRetrievalClaimIndex


async def retrieve_candidates(
    ctx,
    node_input: dict,
) -> dict:
    """
    Retrieve candidate claims for contradiction analysis.

    Input:
        {
            "claims": list[Claim],
            "top_k": int
        }

    Output:
        {
            "claims": list[Claim],
            "candidates": dict[str, list[dict]]
        }
    """
    claims: list[Claim] = node_input["claims"]
    top_k = node_input.get("top_k", 5)

    retrieval = AgentRetrievalClaimIndex()

    candidates: dict[str, list[dict]] = {}

    for claim in claims:
        results = retrieval.search_similar_claims(
            claim,
            top_k=top_k,
        )

        candidates[claim.id] = [
            {
                "claim_id": result.claim_id,
                "distance": result.distance,
            }
            for result in results
        ]

    return {
        "claims": claims,
        "candidates": candidates,
    }