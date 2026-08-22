from __future__ import annotations

from uuid import uuid4

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.conflict import (
    ConflictResolution,
    build_conflict_agent,
)
from app.models.claim import Claim
from app.models.conflict import Conflict
from app.tools.conflict_candidates import ClaimPair


async def evaluate_claim_pair(
    pair: ClaimPair,
) -> ConflictResolution:
    """
    Run the Conflict Agent against one candidate pair.
    """
    agent = build_conflict_agent()

    app_name = "argus"
    user_id = "conflict-analyzer"
    session_id = str(uuid4())

    sessions = InMemorySessionService()

    await sessions.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    runner = Runner(
        app_name=app_name,
        node=agent,
        session_service=sessions,
    )

    async for _ in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text="Determine whether these two claims conflict."
                )
            ],
        ),
        invocation_id=session_id,
        state_delta={
            "claim_a_text": pair.claim_a.text,
            "claim_b_text": pair.claim_b.text,
        },
    ):
        pass

    session = await sessions.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    raw = session.state.get("resolution")

    if raw is None:
        raise RuntimeError(
            "Conflict Agent produced no 'resolution' output"
        )

    return ConflictResolution.model_validate(raw)


async def analyze_claim_pairs(
    pairs: list[ClaimPair],
) -> list[Conflict]:
    """
    Evaluate candidate pairs and return only genuine conflicts.
    """
    conflicts: list[Conflict] = []

    for pair in pairs:
        resolution = await evaluate_claim_pair(pair)

        if not resolution.is_conflict:
            continue

        document_id = pair.claim_a.document_id

        if pair.claim_b.document_id != document_id:
            raise ValueError(
                "Conflict persistence currently requires both claims "
                "to belong to the same document."
            )

        conflicts.append(
            Conflict(
                id=str(uuid4()),
                document_id=document_id,
                claim_a_id=pair.claim_a.id,
                claim_b_id=pair.claim_b.id,
                claim_a_text=pair.claim_a.text,
                claim_b_text=pair.claim_b.text,
                explanation=resolution.explanation,
                severity=resolution.severity,
                confidence=resolution.confidence,
            )
        )

    return conflicts