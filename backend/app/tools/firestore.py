from __future__ import annotations

import os
from typing import Iterable, Iterator
from pydantic import TypeAdapter

from app.models.claim import Claim
from app.models.conflict import Conflict
from app.models.document import DocumentRecord
from app.models.interception import InterceptionRecord
from app.models.issue import Issue, IssueEvent


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
    _shared_client = None

    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore

            # Reuse one Firestore client/channel for the process. Creating a
            # client for every polling request leaks gRPC channels and, on
            # macOS, eventually produces fork-poll warnings or a Python crash.
            if self.__class__._shared_client is None:
                self.__class__._shared_client = firestore.Client(
                    project=os.environ["GOOGLE_CLOUD_PROJECT"],
                    database=os.environ["FIRESTORE_DATABASE"],
                )
            client = self.__class__._shared_client

        self.db = client

    @classmethod
    def close_shared_client(cls) -> None:
        """Close the process-wide client during application shutdown."""
        if cls._shared_client is not None:
            cls._shared_client.close()
            cls._shared_client = None

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

    def update_document_progress(self, document_id: str, progress: float, progress_message: str) -> None:
        """
        Update the progress status of a document record in Firestore.
        """
        doc_ref = self.db.collection("documents").document(document_id)
        doc_ref.update({
            "progress": progress,
            "progress_message": progress_message,
        })

    def get_document(self, document_id: str) -> DocumentRecord | None:
        """
        Retrieve a document record by ID.
        """
        doc_ref = self.db.collection("documents").document(document_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None
        return DocumentRecord.model_validate(snapshot.to_dict())

    def get_document_version(self, document_id: str, version_id: str) -> DocumentRecord | None:
        """
        Retrieve a specific historical version of a document.
        """
        ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("versions")
            .document(version_id)
        )
        snapshot = ref.get()
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

    def get_document_versions(self, document_id: str) -> list[DocumentRecord]:
        """
        List all recorded historical versions of a document.
        """
        versions_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("versions")
        )
        versions = []
        for doc in versions_ref.stream():
            versions.append(DocumentRecord.model_validate(doc.to_dict()))
        # Sort by creation date ascending
        versions.sort(key=lambda d: d.created_at)
        return versions

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

    def get_version_claims(self, document_id: str, version_id: str) -> list[Claim]:
        """
        Retrieve all claims of a specific historical version of a document.
        """
        all_claims = self.get_document_claims(document_id)
        return [c for c in all_claims if c.document_version == version_id]

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

    def save_interception(
        self,
        document_id: str,
        interception: InterceptionRecord,
    ) -> None:
        """
        Log an integrity interception event under:
            documents/{document_id}/interceptions/{interception_id}
        """
        doc_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("interceptions")
            .document(interception.id)
        )
        doc_ref.set(interception.model_dump(mode="json"))

    def save_issues(self, document_id: str, issues: Iterable[Issue]) -> None:
        """
        Save a batch of Issue records under documents/{document_id}/issues/{issue_id}
        """
        parent = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("issues")
        )
        self._commit_in_batches(
            (
                parent.document(issue.id),
                issue.model_dump(mode="json")
            )
            for issue in issues
        )

    def get_issues(self, document_id: str) -> list[Issue]:
        """
        Retrieve all tracked issues for a given document.
        """
        issues_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("issues")
        )
        issues = []
        for doc in issues_ref.stream():
            data = doc.to_dict()
            if "id" not in data:
                data["id"] = doc.id
            issues.append(Issue.model_validate(data))
        return issues

    def save_issue_events(self, document_id: str, events: Iterable[IssueEvent]) -> None:
        """
        Save a batch of IssueEvent records under:
            documents/{document_id}/issue_events/{event_id}
        """
        parent = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("issue_events")
        )
        self._commit_in_batches(
            (
                parent.document(event.id),
                event.model_dump(mode="json")
            )
            for event in events
        )

    def get_issue_events(self, document_id: str) -> list[IssueEvent]:
        """
        Retrieve all tracked issue events for a given document.
        """
        events_ref = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("issue_events")
        )
        events = []
        for doc in events_ref.stream():
            data = doc.to_dict()
            if "id" not in data:
                data["id"] = doc.id
            events.append(IssueEvent.model_validate(data))
        # Sort by created_at ascending
        events.sort(key=lambda e: e.created_at)
        return events

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
