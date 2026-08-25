from __future__ import annotations

import logging

from pydantic import TypeAdapter

from app.models.claim import Claim
from app.tools.claim_retrieval import AgentRetrievalClaimIndex

logger = logging.getLogger(__name__)


async def index_claims(
    ctx,
    node_input: dict,
) -> dict:
    """
    Index claims in Agent Retrieval.

    ADK workflow boundaries may serialize Pydantic models into dictionaries,
    so claims are explicitly rehydrated here before entering the retrieval
    service.
    """

    claims = TypeAdapter(list[Claim]).validate_python(
        node_input["claims"]
    )
    total_claims = len(claims)
    logger.info(f"--- [ADK Workflow] Indexing {total_claims} claims in Agent Retrieval (Vector Search) ---")

    index = AgentRetrievalClaimIndex()

    for idx, claim in enumerate(claims, 1):
        if idx % 5 == 1 or idx == total_claims:
            logger.info(f"    -> Upserting vector index for claim {idx} of {total_claims}...")
        index.upsert_claim(claim)

    logger.info("--- [ADK Workflow] Agent Retrieval indexing complete ---")
    return {
        "record": node_input["record"],
        "claims": claims,
    }