from __future__ import annotations

import os

from google import genai
from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import TypeAdapter

from app.models.claim import ClaimDraft


def extract_claim_drafts_sync(chunk: dict) -> list[ClaimDraft]:
    """Extract claims with the synchronous GenAI client.

    ADK 2.5 currently routes structured LlmAgent output through the GenAI
    async AFC/streaming path.  On macOS that path can leave gRPC fork tasks
    behind and never produce an event.  The synchronous client is the same
    Vertex AI API and is verified to work in the local environment.
    """
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("VERTEX_AI_LOCATION", "asia-south1")
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
    )

    prompt = (
        "Extract only explicit, arguable claims from the document section. "
        "Do not decide whether claims are true and do not invent evidence. "
        "Return an empty JSON array when there are no claims.\n\n"
        f"Chapter: {chunk.get('chapter', '')}\n"
        f"Section: {chunk.get('section', '')}\n"
        f"Document text:\n{chunk['text']}\n\n"
        f"{chunk.get('correction', '')}"
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=TypeAdapter(list[ClaimDraft]).json_schema(),
    )
    response = client.models.generate_content(
        model=os.environ.get("ARGUS_GEMINI_MODEL", "gemini-3.5-flash"),
        contents=prompt,
        config=config,
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty claim extraction response")
    return TypeAdapter(list[ClaimDraft]).validate_json(response.text)


def build_extraction_agent() -> LlmAgent:
    return LlmAgent(
        name="extraction_agent",
        model="gemini-3.5-flash",
        description="Extracts explicit claims from one document section.",
        instruction=(
            "Extract only explicit, arguable claims from the document section. "
            "Do not decide whether claims are true and do not invent evidence. "
            "Return an empty list when there are no claims.\n\n"
            "Chapter: {chapter}\nSection: {section}\n"
            "Document text:\n{chunk_text}\n\n"
            "{correction}"
        ),
        output_schema=list[ClaimDraft],
        output_key="claim_drafts",
        include_contents="none",
    )
