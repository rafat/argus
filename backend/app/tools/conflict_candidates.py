from __future__ import annotations

from dataclasses import dataclass

from app.models.claim import Claim
from app.tools.claim_retrieval import AgentRetrievalClaimIndex


@dataclass(frozen=True)
class ClaimPair:
    """
    Canonical pair of claims to be evaluated for contradiction.

    The ordering is deterministic so (A,B) and (B,A) become
    the same candidate.
    """

    claim_a: Claim
    claim_b: Claim
    retrieval_distance: float

    @property
    def key(self) -> tuple[str, str]:
        return tuple(sorted((self.claim_a.id, self.claim_b.id)))


class ConflictCandidateGenerator:
    """
    Converts semantic retrieval results into unique claim pairs.

    Retrieval only identifies candidates. It does not determine
    whether claims contradict one another.
    """

    def __init__(
        self,
        retrieval: AgentRetrievalClaimIndex | None = None,
    ):
        self.retrieval = retrieval or AgentRetrievalClaimIndex()

    def generate(
        self,
        claims: list[Claim],
        top_k: int = 5,
    ) -> list[ClaimPair]:
        by_id = {
            claim.id: claim
            for claim in claims
        }

        pairs: dict[tuple[str, str], ClaimPair] = {}

        for claim in claims:
            candidates = self.retrieval.search_similar_claims(
                claim,
                top_k=top_k,
            )

            for candidate in candidates:
                other = by_id.get(candidate.claim_id)

                if other is None:
                    # The candidate may belong to another document.
                    #
                    # For Day 3 we only analyze claims that are part
                    # of the current document's claim set.
                    continue

                if other.id == claim.id:
                    continue

                pair_ids = tuple(
                    sorted((claim.id, other.id))
                )

                if pair_ids in pairs:
                    continue

                if claim.id == pair_ids[0]:
                    claim_a = claim
                    claim_b = other
                else:
                    claim_a = other
                    claim_b = claim

                pairs[pair_ids] = ClaimPair(
                    claim_a=claim_a,
                    claim_b=claim_b,
                    retrieval_distance=candidate.distance,
                )

        return list(pairs.values())