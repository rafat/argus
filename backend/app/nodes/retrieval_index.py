from __future__ import annotations

from pydantic import TypeAdapter

from app.models.claim import Claim
from app.tools.claim_retrieval import AgentRetrievalClaimIndex


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

    index = AgentRetrievalClaimIndex()

    for claim in claims:
        index.upsert_claim(claim)

    return {
        "record": node_input["record"],
        "claims": claims,
    }