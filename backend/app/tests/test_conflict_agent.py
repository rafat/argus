import pytest
import os
from pathlib import Path
from dotenv import load_dotenv
from uuid import uuid4
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.conflict import build_conflict_agent, ConflictResolution

# Load .env from project root at import time so env vars are available
load_dotenv(Path(__file__).parents[3] / ".env")


async def _run_conflict_agent(claim_a_text: str, claim_b_text: str) -> ConflictResolution:
    """Run the conflict agent and return the parsed ConflictResolution from session state."""
    agent = build_conflict_agent()
    app_name, user_id, session_id = "argus", "system", str(uuid4())
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=app_name, user_id=user_id, session_id=session_id)

    runner = Runner(
        app_name=app_name,
        node=agent,
        session_service=sessions,
    )

    # Consume the event stream to completion
    async for _ in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="Compare these claims")]),
        invocation_id=session_id,
        state_delta={
            "claim_a_text": claim_a_text,
            "claim_b_text": claim_b_text,
        },
    ):
        pass

    session = await sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    raw = session.state.get("resolution")
    assert raw is not None, "conflict_agent did not write 'resolution' to session state"
    return ConflictResolution.model_validate(raw)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflict_agent_detects_contradiction():
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    resolution = await _run_conflict_agent(
        claim_a_text="Algorithmic curation systematically increases political polarization and erodes democratic norms.",
        claim_b_text="Algorithmic recommendation engines systematically decrease political polarization and improve democratic norms.",
    )

    assert resolution.is_conflict is True
    assert resolution.severity in ("low", "medium", "high")
    assert len(resolution.explanation) > 0
    assert 0.0 <= resolution.confidence <= 1.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflict_agent_no_contradiction():
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        pytest.skip("GOOGLE_CLOUD_PROJECT env var not set")

    resolution = await _run_conflict_agent(
        claim_a_text="Algorithmic curation systematically increases political polarization and erodes democratic norms.",
        claim_b_text="Social platforms amplify outrage because high arousal content drives maximum user engagement.",
    )

    # Both are critical of platforms but complement rather than contradict each other
    assert resolution.is_conflict is False
