from pydantic import TypeAdapter

from app.models.claim import Claim
from app.models.document import DocumentRecord


def persist_result(node_input: dict, repository):
    record = DocumentRecord.model_validate(node_input["record"])

    claims = TypeAdapter(list[Claim]).validate_python(
        node_input["claims"]
    )

    record.status = "processed"

    repository.save_document(record)
    repository.save_claims(record.id, claims)

    return {
        "document": record,
        "claims": claims,
    }