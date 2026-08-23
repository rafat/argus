from __future__ import annotations

import os
from typing import Iterable, Iterator
from pydantic import TypeAdapter

from app.models.claim import Claim
from app.models.conflict import Conflict
from app.models.document import DocumentRecord
from app.models.conflict import Conflict


class FirestoreRepository:
    """
    Firestore persistence layer for Argus.

    Firestore is the canonical store for:
      - documents
      - document versions
      - claims
      - conflict relationships

    Embeddings are deliberately NOT persisted in Firestore.
    They belong in the vector-search index.
    """

    # Firestore supports up to 500 writes per batch.
    # Keep a comfortable margin for future changes.
    _MAX_WRITES_PER_BATCH = 100

    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(
                project=os.environ["GOOGLE_CLOUD_PROJECT"],
                database=os.environ["FIRESTORE_DATABASE"],
            )

        self.db = client

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def save_document(self, document: DocumentRecord) -> None:
        """
        Save the document record and its version record.
        """

        document_data = document.model_dump(mode="json")

        document_ref = (
            self.db
            .collection("documents")
            .document(document.id)
        )

        document_ref.set(document_data)

        (
            document_ref
            .collection("versions")
            .document(document.version_id)
            .set(document_data)
        )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        """
        Retrieve a document record by ID.
        """
        doc_ref = self.db.collection("documents").document(document_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None
        return DocumentRecord.model_validate(snapshot.to_dict())

    def list_documents(self) -> list[DocumentRecord]:
        """
        List all canonical document records in Firestore.
        """
        docs_ref = self.db.collection("documents")
        documents = []
        for doc in docs_ref.stream():
            data = doc.to_dict()
            if "id" not in data:
                data["id"] = doc.id
            documents.append(DocumentRecord.model_validate(data))
        # Sort by creation date descending
        documents.sort(key=lambda d: d.created_at, reverse=True)
        return documents

    def get_document_claims(self, document_id: str) -> list[Claim]:
        """
        Retrieve all claims for a given document_id.
        """
        claims_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("claims")
        )
        claims = []
        for doc in claims_ref.stream():
            data = doc.to_dict()
            if "id" not in data:
                data["id"] = doc.id
            claims.append(Claim.model_validate(data))
        return claims

    def get_conflicts(self, document_id: str) -> list[Conflict]:
        """
        Retrieve all conflicts/contradictions for a given document_id.
        """
        conflicts_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("conflicts")
        )
        conflicts = []
        for doc in conflicts_ref.stream():
            data = doc.to_dict()
            if "id" not in data:
                data["id"] = doc.id
            conflicts.append(Conflict.model_validate(data))
        return conflicts

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def save_claims(
        self,
        document_id: str,
        claims: Iterable[Claim],
    ) -> None:
        """
        Persist claims under:

            documents/{document_id}/claims/{claim_id}

        Embeddings are explicitly excluded from Firestore.

        The embedding belongs to the vector-search layer rather than
        the canonical Claim document.
        """

        claims = TypeAdapter(
                list[Claim]
            ).validate_python(
                list(claims)
            )

        parent = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("claims")
        )

        def writes() -> Iterator[tuple]:
            for claim in claims:
                data = claim.model_dump(
                    mode="json",
                    exclude={"embedding"},
                )

                yield (
                    parent.document(claim.id),
                    data,
                )

        self._commit_in_batches(writes())

    def get_claim(
        self,
        document_id: str,
        claim_id: str,
    ) -> Claim | None:
        ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("claims")
            .document(claim_id)
        )

        snapshot = ref.get()

        if not snapshot.exists:
            return None

        return Claim.model_validate(snapshot.to_dict())

    def get_claim_by_id(self, claim_id: str) -> Claim | None:
        """
        Look up a claim by ID across the Firestore claim collections.

        This is acceptable for the Day 3 prototype. For a larger corpus,
        maintain a top-level claim lookup collection or include enough
        routing metadata in the retrieval result.
        """
        from google.cloud import firestore

        query = (
            self.db
            .collection_group("claims")
            .where(
                filter=firestore.FieldFilter(
                    "id",
                    "==",
                    claim_id,
                )
            )
            .limit(1)
        )

        for snapshot in query.stream():
            return Claim.model_validate(snapshot.to_dict())

        return None

    def get_claims(
        self,
        document_id: str,
        claim_ids: Iterable[str],
    ) -> list[Claim]:
        claims: list[Claim] = []

        for claim_id in claim_ids:
            claim = self.get_claim(
                document_id,
                claim_id,
            )

            if claim is not None:
                claims.append(claim)

        return claims

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def save_conflicts(
        self,
        document_id: str,
        conflicts: Iterable[Conflict],
    ) -> None:
        conflicts = list(conflicts)

        parent = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("conflicts")
        )

        self._commit_in_batches(
            (
                parent.document(conflict.id),
                conflict.model_dump(mode="json"),
            )
            for conflict in conflicts
        )

    # ------------------------------------------------------------------
    # Batch helper
    # ------------------------------------------------------------------

    def _commit_in_batches(
        self,
        writes: Iterable[tuple],
    ) -> None:
        """
        Commit Firestore writes in bounded batches.

        `writes` should yield:

            (DocumentReference, dictionary)
        """

        batch = self.db.batch()
        writes_in_batch = 0

        for document_ref, data in writes:
            batch.set(document_ref, data)
            writes_in_batch += 1

            if writes_in_batch >= self._MAX_WRITES_PER_BATCH:
                batch.commit()

                batch = self.db.batch()
                writes_in_batch = 0

        if writes_in_batch:
            batch.commit()