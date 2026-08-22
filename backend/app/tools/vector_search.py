from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from google import genai

from app.models.claim import Claim


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


# ---------------------------------------------------------------------------
# Retrieval result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimilarClaim:
    """A claim returned by semantic retrieval."""

    claim: Claim
    score: float


# ---------------------------------------------------------------------------
# Vector utilities
# ---------------------------------------------------------------------------

def cosine_similarity(
    v1: list[float],
    v2: list[float],
) -> float:
    """
    Calculate cosine similarity between two vectors.

    Returns:
        A value in [-1, 1].

    Raises:
        ValueError: If the vectors have different dimensions.
    """
    if len(v1) != len(v2):
        raise ValueError(
            f"Vector dimensions do not match: {len(v1)} != {len(v2)}"
        )

    if not v1:
        return 0.0

    arr1 = np.asarray(v1, dtype=np.float32)
    arr2 = np.asarray(v2, dtype=np.float32)

    norm1 = np.linalg.norm(arr1)
    norm2 = np.linalg.norm(arr2)

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return float(np.dot(arr1, arr2) / (norm1 * norm2))


# ---------------------------------------------------------------------------
# Embedding service
# ---------------------------------------------------------------------------

class EmbeddingService:
    """
    Generates embeddings for Argus claims.

    This class deliberately knows nothing about Firestore or Vector Search.

    Firestore stores canonical claims.
    A vector index stores/retrieves their embeddings.
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
    ):
        self.model = model or _env(
            "EMBEDDING_MODEL",
            DEFAULT_EMBEDDING_MODEL,
        )

        self.dimensions = int(
            _env("EMBEDDING_DIMENSIONS", "3072")
        )

        if not self.model:
            raise RuntimeError("EMBEDDING_MODEL must not be empty")

        if client is None:
            project_id = _env("GOOGLE_CLOUD_PROJECT")
            location = _env(
                "VERTEX_AI_LOCATION",
                "asia-south1",
            )

            if not project_id:
                raise RuntimeError(
                    "GOOGLE_CLOUD_PROJECT is required for embeddings"
                )

            client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location,
            )

        self.client = client

    def embed(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[float]:
        """
        Generate an embedding suitable for semantic retrieval.

        RETRIEVAL_DOCUMENT is used for claims stored in the vector index.
        RETRIEVAL_QUERY should be used for search queries.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        response = self.client.models.embed_content(
            model=self.model,
            contents=text,
            config={
                "task_type": task_type,
                "output_dimensionality": self.dimensions,
            },
        )

        if not response.embeddings:
            raise RuntimeError(
                f"Embedding model {self.model!r} returned no embeddings"
            )

        values = response.embeddings[0].values

        if not values:
            raise RuntimeError(
                f"Embedding model {self.model!r} returned an empty vector"
            )

        return [float(value) for value in values]

    def embed_claim(self, claim: Claim) -> list[float]:
        return self.embed(
            claim.text,
            task_type="RETRIEVAL_DOCUMENT",
        )

    def embed_query(self, text: str) -> list[float]:
        return self.embed(
            text,
            task_type="RETRIEVAL_QUERY",
        )

    def embed_claims(
        self,
        claims: Iterable[Claim],
    ) -> dict[str, list[float]]:
        """
        Generate embeddings for multiple claims.

        Returns:
            Mapping of claim ID -> embedding.
        """
        embeddings: dict[str, list[float]] = {}

        for claim in claims:
            embeddings[claim.id] = self.embed_claim(claim)

        return embeddings


# ---------------------------------------------------------------------------
# Local vector index
# ---------------------------------------------------------------------------

class LocalClaimVectorIndex:
    """
    Temporary in-process vector index.

    This is NOT Vertex AI Vector Search.

    It exists so that Argus can validate:
        Claim -> embedding -> nearest-neighbor retrieval

    before introducing the managed Vector Search infrastructure.

    The class intentionally operates on Claim objects so that it can later
    be replaced by VertexClaimVectorIndex without changing the relationship
    analysis layer.
    """

    def __init__(self):
        self._claims: dict[str, Claim] = {}

    def add(self, claim: Claim) -> None:
        """Add or replace a claim in the local index."""
        if not claim.embedding:
            raise ValueError(
                f"Claim {claim.id} does not contain an embedding"
            )

        self._claims[claim.id] = claim

    def add_many(self, claims: Iterable[Claim]) -> None:
        """Add multiple claims."""
        for claim in claims:
            self.add(claim)

    def remove(self, claim_id: str) -> None:
        """Remove a claim from the local index if present."""
        self._claims.pop(claim_id, None)

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        min_score: float = 0.5,
        exclude_claim_id: str | None = None,
    ) -> list[SimilarClaim]:
        """
        Retrieve the nearest claims using cosine similarity.

        This performs an exhaustive local scan and is intentionally simple.
        It should NOT be used as the production retrieval implementation.
        """
        if not query_embedding:
            return []

        if top_k <= 0:
            return []

        results: list[SimilarClaim] = []

        for claim in self._claims.values():
            if exclude_claim_id and claim.id == exclude_claim_id:
                continue

            if not claim.embedding:
                continue

            score = cosine_similarity(
                query_embedding,
                claim.embedding,
            )

            if score >= min_score:
                results.append(
                    SimilarClaim(
                        claim=claim,
                        score=score,
                    )
                )

        results.sort(
            key=lambda result: result.score,
            reverse=True,
        )

        return results[:top_k]

    def search_claim(
        self,
        target_claim: Claim,
        *,
        top_k: int = 5,
        min_score: float = 0.5,
    ) -> list[SimilarClaim]:
        """Find claims similar to an existing claim."""
        if not target_claim.embedding:
            return []

        return self.search(
            target_claim.embedding,
            top_k=top_k,
            min_score=min_score,
            exclude_claim_id=target_claim.id,
        )

    @property
    def size(self) -> int:
        """Number of indexed claims."""
        return len(self._claims)


# ---------------------------------------------------------------------------
# Compatibility facade
# ---------------------------------------------------------------------------

class VectorSearchService:
    """
    Argus vector-search facade.

    For now this combines:
        1. Embedding generation
        2. Local vector retrieval

    Later this facade can delegate retrieval to Vertex AI Vector Search
    without changing callers elsewhere in the application.
    """

    def __init__(
        self,
        client: Any | None = None,
        embedding_model: str | None = None,
        index: LocalClaimVectorIndex | None = None,
    ):
        self.embeddings = EmbeddingService(
            client=client,
            model=embedding_model,
        )

        self.index = index or LocalClaimVectorIndex()

    def get_embedding(self, text: str) -> list[float]:
        """
        Backwards-compatible alias for embedding generation.
        """
        return self.embeddings.embed(text)

    def embed_claim(self, claim: Claim) -> list[float]:
        """Generate an embedding for a claim."""
        return self.embeddings.embed_claim(claim)

    def index_claim(self, claim: Claim) -> Claim:
        """
        Generate an embedding and add the claim to the local index.

        The embedding is also attached to the Claim object for the current
        prototype. Once Vertex AI Vector Search is introduced, embeddings
        should no longer be persisted as part of the Firestore Claim.
        """
        claim.embedding = self.embed_claim(claim)
        self.index.add(claim)
        return claim

    def index_claims(
        self,
        claims: Iterable[Claim],
    ) -> list[Claim]:
        """Generate embeddings and index multiple claims."""
        indexed: list[Claim] = []

        for claim in claims:
            indexed.append(self.index_claim(claim))

        return indexed

    def query_similar_claims(
        self,
        target_claim: Claim,
        candidate_claims: list[Claim] | None = None,
        *,
        limit: int = 5,
        min_score: float = 0.5,
    ) -> list[tuple[Claim, float]]:
        """
        Retrieve semantically similar claims.

        `candidate_claims` is retained for backwards compatibility with
        the original prototype tests.

        If candidate_claims is supplied, retrieval is performed against
        that list. Otherwise the internal local index is searched.
        """
        if not target_claim.embedding:
            raise ValueError(
                f"Target claim {target_claim.id} does not contain an embedding"
            )

        if candidate_claims is not None:
            results: list[tuple[Claim, float]] = []

            for claim in candidate_claims:
                if claim.id == target_claim.id:
                    continue

                if not claim.embedding:
                    continue

                score = cosine_similarity(
                    target_claim.embedding,
                    claim.embedding,
                )

                if score >= min_score:
                    results.append((claim, score))

            results.sort(
                key=lambda item: item[1],
                reverse=True,
            )

            return results[:limit]

        results = self.index.search_claim(
            target_claim,
            top_k=limit,
            min_score=min_score,
        )

        return [
            (result.claim, result.score)
            for result in results
        ]