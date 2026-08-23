from app.models.claim import Claim
from app.models.conflict import Conflict

from app.tools.firestore import FirestoreRepository


class FakeBatch:
    def __init__(self, commits):
        self.commits = commits
        self.write_count = 0

    def set(self, _document_ref, _data):
        self.write_count += 1

    def commit(self):
        self.commits.append(self.write_count)


class FakeDocument:
    def document(self, _document_id):
        return self

    def collection(self, _collection_name):
        return self


class FakeFirestoreClient:
    def __init__(self):
        self.commit_sizes = []

    def batch(self):
        return FakeBatch(self.commit_sizes)

    def collection(self, _collection_name):
        return FakeDocument()


def test_save_claims_splits_large_writes_into_batches():
    client = FakeFirestoreClient()
    repository = FirestoreRepository(client=client)
    claims = [
        Claim(
            id=str(index),
            document_id="document-1",
            document_version="version-1",
            chapter="Chapter 1",
            section="1.1",
            text=f"Claim {index}",
            embedding=[0.1, 0.2],
        )
        for index in range(205)
    ]

    repository.save_claims("document-1", claims)

    assert client.commit_sizes == [100, 100, 5]


class FakeDoc:
    def __init__(self, id, data):
        self.id = id
        self._data = data

    def to_dict(self):
        return self._data


def test_firestore_repository_get_methods():
    class CustomFakeDocument:
        def __init__(self):
            self.doc_id = None
            self.collection_name = None

        def document(self, doc_id):
            self.doc_id = doc_id
            return self

        def collection(self, collection_name):
            self.collection_name = collection_name
            return self

        def get(self):
            class Snapshot:
                exists = True
                def to_dict(self):
                    return {
                        "id": "doc-1",
                        "version_id": "v-1",
                        "filename": "test.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 100,
                        "status": "processed",
                    }
            return Snapshot()

        def stream(self):
            if self.collection_name == "claims":
                return [
                    FakeDoc("claim-1", {
                        "text": "Claim 1",
                        "document_id": "doc-1",
                        "document_version": "v-1",
                        "chapter": "Ch 1",
                        "section": "1.1",
                    })
                ]
            elif self.collection_name == "conflicts":
                return [
                    FakeDoc("conflict-1", {
                        "document_id": "doc-1",
                        "claim_a_id": "claim-1",
                        "claim_b_id": "claim-2",
                        "claim_a_text": "Claim 1",
                        "claim_b_text": "Claim 2",
                        "explanation": "Contradiction",
                        "severity": "high",
                        "confidence": 0.9,
                    })
                ]
            return []

    class CustomFakeFirestoreClient:
        def collection(self, _collection_name):
            return CustomFakeDocument()

    client = CustomFakeFirestoreClient()
    repo = FirestoreRepository(client=client)

    doc = repo.get_document("doc-1")
    assert doc is not None
    assert doc.id == "doc-1"
    assert doc.status == "processed"

    claims = repo.get_document_claims("doc-1")
    assert len(claims) == 1
    assert claims[0].id == "claim-1"
    assert claims[0].text == "Claim 1"

    conflicts = repo.get_conflicts("doc-1")
    assert len(conflicts) == 1
    assert conflicts[0].id == "conflict-1"
    assert conflicts[0].severity == "high"

def test_save_conflicts():
    repository = FirestoreRepository(
        client=FakeFirestoreClient(),
    )

    conflict = Conflict(
        id="conflict-1",
        document_id="doc-1",
        claim_a_id="claim-a",
        claim_b_id="claim-b",
        claim_a_text="Claim A",
        claim_b_text="Claim B",
        explanation="The claims assert opposite outcomes.",
        severity="high",
        confidence=0.95,
    )

    repository.save_conflicts(
        "doc-1",
        [conflict],
    )


