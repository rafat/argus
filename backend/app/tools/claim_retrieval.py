from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import vectorsearch_v1

from app.models.claim import Claim
from app.tools.vector_search import EmbeddingService


@dataclass(frozen=True)
class RetrievalCandidate:
    """A candidate claim returned by Agent Retrieval."""

    claim_id: str
    distance: float
    document_id: str | None = None
    document_version: str | None = None
    text: str | None = None


class AgentRetrievalClaimIndex:
    """
    Agent Retrieval-backed claim index.

    Agent Retrieval is a retrieval projection.
    Firestore remains the canonical source of Claim objects.
    """

    def __init__(
        self,
        client=None,
        search_client=None,
        embedding_service: EmbeddingService | None = None,
        project_id: str | None = None,
        location: str | None = None,
        collection_id: str | None = None,
        vector_field: str | None = None,
    ):
        self.project_id = project_id or os.environ["GOOGLE_CLOUD_PROJECT"]

        self.location = location or os.environ.get(
            "AGENT_RETRIEVAL_LOCATION",
            "us-central1",
        )

        self.collection_id = collection_id or os.environ[
            "AGENT_RETRIEVAL_COLLECTION_ID"
        ]

        self.vector_field = vector_field or os.environ.get(
            "AGENT_RETRIEVAL_VECTOR_FIELD",
            "claim_embedding",
        )

        self.client = client or vectorsearch_v1.DataObjectServiceClient()

        self.search_client = (
            search_client
            or vectorsearch_v1.DataObjectSearchServiceClient()
        )

        self.embeddings = embedding_service or EmbeddingService()

    @property
    def collection_name(self) -> str:
        return (
            f"projects/{self.project_id}"
            f"/locations/{self.location}"
            f"/collections/{self.collection_id}"
        )

    def _data_object_name(self, claim_id: str) -> str:
        return (
            f"{self.collection_name}"
            f"/dataObjects/{claim_id}"
        )

    def _data_for_claim(self, claim: Claim) -> dict:
        return {
            "claim_id": claim.id,
            "document_id": claim.document_id,
            "document_version": claim.document_version,
            "text": claim.text,
            "chapter": claim.chapter,
            "section": claim.section,
            "status": claim.status,
            "confidence": claim.confidence,
        }

    def _build_data_object(
        self,
        claim: Claim,
        embedding: list[float],
    ) -> vectorsearch_v1.DataObject:
        return vectorsearch_v1.DataObject(
            name=self._data_object_name(claim.id),
            data=self._data_for_claim(claim),
            vectors={
                self.vector_field: {
                    "dense": {
                        "values": embedding,
                    }
                }
            },
        )

    def upsert_claim(self, claim: Claim) -> None:
        """
        Create or update a Claim Data Object.

        This makes ingestion idempotent: re-processing the same Claim
        ID updates the retrieval projection rather than failing.
        """
        embedding = self.embeddings.embed_claim(claim)

        if len(embedding) != self.embeddings.dimensions:
            raise ValueError(
                f"Expected {self.embeddings.dimensions}-dimensional "
                f"embedding, got {len(embedding)}"
            )

        data_object = self._build_data_object(
            claim,
            embedding,
        )

        create_request = vectorsearch_v1.CreateDataObjectRequest(
            parent=self.collection_name,
            data_object_id=claim.id,
            data_object=data_object,
        )

        try:
            self.client.create_data_object(
                request=create_request,
            )
            return

        except AlreadyExists:
            pass

        update_request = vectorsearch_v1.UpdateDataObjectRequest(
            data_object=data_object,
        )

        self.client.update_data_object(
            request=update_request,
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        """
        Find semantically similar claims.

        The query uses the RETRIEVAL_QUERY embedding task.
        """
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")

        query_embedding = self.embeddings.embed_query(query)

        if len(query_embedding) != self.embeddings.dimensions:
            raise ValueError(
                f"Expected {self.embeddings.dimensions}-dimensional "
                f"query embedding, got {len(query_embedding)}"
            )

        vector_search = vectorsearch_v1.VectorSearch(
            search_field=self.vector_field,
            vector={
                "values": query_embedding,
            },
            top_k=top_k,
            output_fields={
                "data_fields": "*",
            },
        )

        request = vectorsearch_v1.SearchDataObjectsRequest(
            parent=self.collection_name,
            vector_search=vector_search,
        )

        response = self.search_client.search_data_objects(
            request=request,
        )

        candidates: list[RetrievalCandidate] = []

        for result in response.results:
            data_object = result.data_object
            data = dict(data_object.data)

            raw_name = getattr(data_object, "name", "")
            name_tail = (
                raw_name.rsplit("/", 1)[-1]
                if isinstance(raw_name, str) and "/" in raw_name
                else (raw_name if isinstance(raw_name, str) else "")
            )

            claim_id = (
                getattr(data_object, "data_object_id", None)
                or data.get("claim_id")
                or name_tail
            )

            if not claim_id or not str(claim_id).strip():
                logger.warning(
                    "[ClaimRetrieval] Skipping candidate with unresolved claim_id "
                    f"(data_object={data_object!r})"
                )
                continue

            candidates.append(
                RetrievalCandidate(
                    claim_id=str(claim_id).strip(),
                    distance=float(result.distance),
                    document_id=data.get("document_id"),
                    document_version=data.get("document_version"),
                    text=data.get("text"),
                )
            )

        return candidates

    def search_similar_claims(
        self,
        claim: Claim,
        top_k: int = 10,
    ) -> list[RetrievalCandidate]:
        """
        Find claims semantically similar to an existing Claim.

        The target claim itself is excluded.
        """
        candidates = self.search(
            query=claim.text,
            top_k=top_k + 1,
        )

        return [
            candidate
            for candidate in candidates
            if candidate.claim_id != claim.id
        ][:top_k]

    def delete_claim(self, claim_id: str) -> None:
        """Delete a Claim Data Object."""
        request = vectorsearch_v1.DeleteDataObjectRequest(
            name=self._data_object_name(claim_id),
        )

        try:
            self.client.delete_data_object(
                request=request,
            )
        except NotFound:
            # Idempotent cleanup.
            pass