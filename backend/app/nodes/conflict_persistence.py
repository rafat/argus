from __future__ import annotations

import logging

from pydantic import TypeAdapter

from app.models.conflict import Conflict
from app.models.document import DocumentRecord

logger = logging.getLogger(__name__)


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

    logger.info(f"--- [ADK Workflow] Saving {len(conflicts)} verified conflicts to Firestore ---")
    repository.save_conflicts(
        record.id,
        conflicts,
    )
    logger.info("--- [ADK Workflow] Conflict persistence complete. Workflow finished successfully! ---")

    return {
        "record": record,
        "claims": node_input["claims"],
        "candidate_pairs": node_input.get(
            "candidate_pairs",
            [],
        ),
        "conflicts": conflicts,
    }