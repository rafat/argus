from __future__ import annotations

from pydantic import TypeAdapter

from app.models.conflict import Conflict
from app.models.document import DocumentRecord


def persist_conflicts(
    node_input: dict,
    repository,
) -> dict:

    record = DocumentRecord.model_validate(
        node_input["record"]
    )

    conflicts = TypeAdapter(list[Conflict]).validate_python(
        node_input.get("conflicts", [])
    )

    repository.save_conflicts(
        record.id,
        conflicts,
    )

    return {
        "record": record,
        "claims": node_input["claims"],
        "candidate_pairs": node_input.get(
            "candidate_pairs",
            [],
        ),
        "conflicts": conflicts,
    }