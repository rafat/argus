from __future__ import annotations

import os
from typing import Iterable
from pydantic import TypeAdapter

from app.models.claim import Claim
from app.models.document import DocumentRecord


class FirestoreRepository:
    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(
                project=os.environ["GOOGLE_CLOUD_PROJECT"],
                database=os.environ["FIRESTORE_DATABASE"],
            )
        self.db = client

    def save_document(self, document: DocumentRecord) -> None:
        self.db.collection("documents").document(document.id).set(document.model_dump(mode="json"))
        self.db.collection("documents").document(document.id).collection("versions").document(document.version_id).set(document.model_dump(mode="json"))

    def save_claims(self, document_id: str, claims: Iterable[Claim]) -> None:
        claims = TypeAdapter(list[Claim]).validate_python(list(claims))

        batch = self.db.batch()

        parent = (
            self.db
            .collection("documents")
            .document(document_id)
            .collection("claims")
        )

        for claim in claims:
            batch.set(
                parent.document(claim.id),
                claim.model_dump(mode="json"),
            )

        batch.commit()
