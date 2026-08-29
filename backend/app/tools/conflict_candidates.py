import logging
import os
from dataclasses import dataclass

import numpy as np

from app.models.claim import Claim
from app.tools.claim_retrieval import AgentRetrievalClaimIndex

logger = logging.getLogger(__name__)


@dataclass(frozen=True, init=False)
class ClaimPair:
    """
    Canonical pair of claims to be evaluated for contradiction.

    The ordering is deterministic so (A,B) and (B,A) become
    the same candidate.
    """

    claim_a: Claim
    claim_b: Claim
    retrieval_score: float

    def __init__(
        self,
        claim_a: Claim,
        claim_b: Claim,
        retrieval_score: float | None = None,
        *,
        retrieval_distance: float | None = None,
    ):
        """Create a pair while accepting the pre-score field name."""
        if retrieval_score is None and retrieval_distance is None:
            raise TypeError(
                "ClaimPair requires retrieval_score or retrieval_distance"
            )
        if retrieval_score is not None and retrieval_distance is not None:
            raise TypeError(
                "Specify only retrieval_score or retrieval_distance"
            )
        object.__setattr__(
            self,
            "claim_a",
            claim_a,
        )
        object.__setattr__(
            self,
            "claim_b",
            claim_b,
        )
        object.__setattr__(
            self,
            "retrieval_score",
            float(
                retrieval_score
                if retrieval_score is not None
                else retrieval_distance
            ),
        )

    @property
    def retrieval_distance(self) -> float:
        """Backwards-compatible alias for retrieval_score."""
        return self.retrieval_score

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
        default_min_score: float | None = None,
    ):
        self._retrieval = retrieval
        if default_min_score is not None:
            self._default_min_score = default_min_score
        else:
            try:
                self._default_min_score = float(
                    os.environ.get("CONFLICT_MIN_SIMILARITY_SCORE", "0.5")
                )
            except ValueError:
                self._default_min_score = 0.5

    @property
    def retrieval(self) -> AgentRetrievalClaimIndex:
        if self._retrieval is None:
            self._retrieval = AgentRetrievalClaimIndex()
        return self._retrieval

    def _compute_vectorized_pairs(
        self,
        claims: list[Claim],
        top_k: int,
        min_score: float,
        batch_size: int = 512,
    ) -> dict[tuple[str, str], ClaimPair]:
        """Compute nearest neighbors with bounded matrix memory."""
        if not claims or top_k <= 0:
            return {}
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")

        embeddings = np.array([c.embedding for c in claims], dtype=np.float32)
        if embeddings.ndim != 2:
            raise ValueError("All claim embeddings must be non-empty vectors")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = embeddings / norms

        pairs: dict[tuple[str, str], ClaimPair] = {}
        for start in range(0, len(claims), batch_size):
            end = min(start + batch_size, len(claims))
            similarity_batch = np.dot(
                normalized[start:end],
                normalized.T,
            )

            for batch_index, row in enumerate(similarity_batch):
                i = start + batch_index
                row = row.copy()
                row[i] = -1.0
                valid_indices = np.where(row >= min_score)[0]
                if len(valid_indices) == 0:
                    continue

                sorted_sub = valid_indices[np.argsort(-row[valid_indices])[:top_k]]
                claim = claims[i]
                for j in sorted_sub:
                    other = claims[j]
                    if other.id == claim.id:
                        continue

                    pair_ids = tuple(sorted((claim.id, other.id)))
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
                        retrieval_score=float(row[j]),
                    )

        return pairs

    def generate_local(
        self,
        claims: list[Claim],
        top_k: int = 5,
        min_score: float | None = None,
    ) -> list[ClaimPair]:
        """
        Generate candidate pairs using in-memory embeddings for intra-document analysis.
        Uses vectorized matrix multiplication for high performance.
        """
        if min_score is None:
            min_score = self._default_min_score

        valid_claims = [c for c in claims if c.embedding]
        logger.info(
            f"[ConflictCandidates] Local generation: {len(valid_claims)} of {len(claims)} claims have embeddings (min_score={min_score:.2f}, top_k={top_k})"
        )
        if not valid_claims:
            return []

        pairs = self._compute_vectorized_pairs(valid_claims, top_k, min_score)
        logger.info(
            f"[ConflictCandidates] Local generation found {len(pairs)} unique candidate pairs across {len(valid_claims)} claims"
        )
        return list(pairs.values())

    def generate_remote(
        self,
        claims: list[Claim],
        all_doc_claims: list[Claim] | None = None,
        top_k: int = 5,
        min_score: float | None = None,
    ) -> list[ClaimPair]:
        if min_score is None:
            min_score = self._default_min_score
        if top_k <= 0:
            return []
        doc_claims = all_doc_claims or claims
        by_id = {claim.id: claim for claim in doc_claims}

        pairs: dict[tuple[str, str], ClaimPair] = {}
        raw_candidates_total = 0
        same_doc_matches = 0
        external_skipped = 0

        for claim in claims:
            candidates = self.retrieval.search_similar_claims(
                claim,
                top_k=top_k,
            )
            raw_candidates_total += len(candidates)

            for candidate in candidates:
                other = by_id.get(candidate.claim_id)

                if other is None:
                    external_skipped += 1
                    continue

                if other.id == claim.id:
                    continue

                same_doc_matches += 1
                pair_ids = tuple(sorted((claim.id, other.id)))

                if pair_ids in pairs:
                    continue

                if claim.id == pair_ids[0]:
                    claim_a = claim
                    claim_b = other
                else:
                    claim_a = other
                    claim_b = claim

                # Normalize distance to similarity score if distance is 0..1
                sim_score = (
                    max(0.0, 1.0 - candidate.distance)
                    if 0.0 <= candidate.distance <= 1.0
                    else candidate.distance
                )
                if sim_score < min_score:
                    continue

                pairs[pair_ids] = ClaimPair(
                    claim_a=claim_a,
                    claim_b=claim_b,
                    retrieval_score=sim_score,
                )

        logger.info(
            f"[ConflictCandidates] Remote retrieval: {raw_candidates_total} raw candidates returned, "
            f"{same_doc_matches} matched current document claims, {external_skipped} discarded (external/unmatched), "
            f"{len(pairs)} unique candidate pairs formed."
        )
        return list(pairs.values())

    def generate(
        self,
        claims: list[Claim],
        top_k: int = 5,
        min_score: float | None = None,
    ) -> list[ClaimPair]:
        if not claims:
            return []

        embedded_claims = [c for c in claims if c.embedding]
        missing_claims = [c for c in claims if not c.embedding]

        all_pairs: dict[tuple[str, str], ClaimPair] = {}

        # 1. Process claims with embeddings via fast local vectorized search
        if embedded_claims:
            logger.info(
                f"[ConflictCandidates] Using in-memory embeddings for candidate pairing ({len(embedded_claims)}/{len(claims)} claims)"
            )
            local_pairs = self.generate_local(
                embedded_claims,
                top_k=top_k,
                min_score=min_score,
            )
            for p in local_pairs:
                all_pairs[p.key] = p

        # 2. Process claims lacking embeddings via remote retrieval against the document
        if missing_claims:
            logger.info(
                f"[ConflictCandidates] {len(missing_claims)} claims lack embeddings; querying remote Agent Retrieval"
            )
            remote_pairs = self.generate_remote(
                claims=missing_claims,
                all_doc_claims=claims,
                top_k=top_k,
                min_score=min_score,
            )
            for p in remote_pairs:
                if p.key not in all_pairs:
                    all_pairs[p.key] = p

        logger.info(
            f"[ConflictCandidates] Total unique candidate pairs generated: {len(all_pairs)}"
        )
        return list(all_pairs.values())
