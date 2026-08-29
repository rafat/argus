from __future__ import annotations

import asyncio
import logging
import os
from uuid import uuid4

from google import genai
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import TypeAdapter

from app.agents.conflict import (
    ConflictResolution,
    build_conflict_agent,
)
from app.models.claim import Claim
from app.models.conflict import Conflict
from app.tools.conflict_candidates import ClaimPair


def evaluate_claim_pair_sync(pair: ClaimPair) -> ConflictResolution:
    """Evaluate a conflict with the synchronous Vertex client."""
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("VERTEX_AI_LOCATION", "asia-south1"),
    )
    prompt = (
        "Compare the following two claims extracted from the same document.\n\n"
        f"Claim A: {pair.claim_a.text}\n"
        f"Claim B: {pair.claim_b.text}\n\n"
        "Determine whether they genuinely contradict or conflict semantically. "
        "Similarity alone is not contradiction. Explain the reasoning."
    )
    response = client.models.generate_content(
        model=os.environ.get("ARGUS_GEMINI_MODEL", "gemini-3.5-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TypeAdapter(ConflictResolution).json_schema(),
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty conflict analysis response")
    return ConflictResolution.model_validate_json(response.text)


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
    logger = logging.getLogger(__name__)

    for idx, pair in enumerate(pairs, 1):
        logger.info(
            f"[ConflictAnalysis] Evaluating pair {idx}/{len(pairs)}: "
            f"'{pair.claim_a.text[:40]}...' vs '{pair.claim_b.text[:40]}...'"
        )
        use_async_gemini = os.environ.get(
            "ARGUS_USE_ASYNC_GEMINI", "false"
        ).lower() in {"1", "true", "yes"}
        if use_async_gemini:
            resolution = await evaluate_claim_pair(pair)
        else:
            resolution = await asyncio.to_thread(
                evaluate_claim_pair_sync,
                pair,
            )

        if not resolution.is_conflict:
            logger.info(f"[ConflictAnalysis] Pair {idx}/{len(pairs)}: No conflict detected.")
            continue

        document_id = pair.claim_a.document_id

        if pair.claim_b.document_id != document_id:
            raise ValueError(
                "Conflict persistence currently requires both claims "
                "to belong to the same document."
            )

        logger.info(
            f"[ConflictAnalysis] Pair {idx}/{len(pairs)}: Genuine conflict identified! "
            f"(severity={resolution.severity}, confidence={resolution.confidence:.2f})"
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

    logger.info(
        f"[ConflictAnalysis] Finished evaluating {len(pairs)} candidate pairs. "
        f"Found {len(conflicts)} verified conflicts."
    )
    return conflicts
