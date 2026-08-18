from __future__ import annotations

from datetime import datetime, timezone
from pydantic import TypeAdapter
from uuid import uuid4

from google.adk.workflow import FunctionNode, START, Workflow
from google.adk.workflow import RetryConfig

from app.agents.extraction import build_extraction_agent
from app.models.claim import Claim, ClaimDraft
from app.models.document import DocumentRecord
from app.nodes.parsing import parse_upload
from app.nodes.persistence import persist_result
from app.nodes.validation import request_correction, validate_claims


def _materialize_claims(node_input, chunk: dict) -> list[Claim]:
    drafts = TypeAdapter(list[ClaimDraft]).validate_python(node_input)

    return [
        Claim(
            **draft.model_dump(),
            id=str(uuid4()),
            document_id=chunk["document_id"],
            document_version=chunk["document_version"],
            chapter=chunk.get("chapter", ""),
            section=chunk.get("section", ""),
            source_span=chunk.get("text", "")[:500],
        )
        for draft in drafts
    ]


def build_chunk_workflow() -> Workflow:
    """ADK graph for one chunk: extract -> validate -> correct/retry."""
    seed = FunctionNode(
        func=lambda ctx, node_input: _seed_chunk(ctx, node_input),
        name="seed_chunk",
    )
    extraction = build_extraction_agent()
    extraction.retry_config = RetryConfig(max_attempts=3, initial_delay=0.1, jitter=0)
    validation = FunctionNode(
        func=validate_claims,
        name="validate_claims",
    )
    validation.input_schema = list[ClaimDraft]
    validation.output_schema = list[ClaimDraft]
    correction = FunctionNode(
        func=request_correction,
        name="request_correction",
    )
    correction.input_schema = list[ClaimDraft]
    correction.output_schema = dict
    return Workflow(
        name="chunk_extraction_workflow",
        edges=[
            (START, seed, extraction, validation),
            (validation, {"valid": _chunk_result_node(),
                "invalid": correction}),
            (correction, extraction),
        ],
    )


def _return_drafts(node_input: list[ClaimDraft]) -> list[ClaimDraft]:
    return node_input


def _chunk_result_node() -> FunctionNode:
    result = FunctionNode(func=_return_drafts, name="chunk_result")
    result.input_schema = list[ClaimDraft]
    result.output_schema = list[ClaimDraft]
    return result


def _seed_chunk(ctx, node_input: dict) -> dict:
    ctx.state["chapter"] = node_input.get("chapter", "")
    ctx.state["section"] = node_input.get("section", "")
    ctx.state["chunk_text"] = node_input["text"]
    ctx.state["correction"] = ""
    ctx.state["chunk"] = node_input
    return {}


def build_document_workflow(repository) -> Workflow:
    """Build the ADK document graph; parsing and persistence remain Python nodes."""
    parse = FunctionNode(func=parse_upload, name="parse_document")

    async def extract_all(ctx, node_input: dict) -> dict:
        claims: list[Claim] = []

        chunk_workflow = build_chunk_workflow()

        for chunk in node_input["chunks"]:
            chunk_data = chunk.model_dump()

            drafts = await ctx.run_node(
                chunk_workflow,
                node_input=chunk_data,
            )

            claims.extend(
                _materialize_claims(
                    drafts,
                    chunk_data,
                )
            )

        return {
            "record": node_input["record"],
            "claims": claims,
        }

    extract = FunctionNode(func=extract_all, name="extract_chunks", rerun_on_resume=True)
    extract.output_schema = dict
    persist = FunctionNode(
        func=lambda node_input: persist_result(node_input, repository),
        name="persist_claims",
    )
    persist.input_schema = dict
    persist.output_schema = dict
    return Workflow(name="document_workflow", edges=[(START, parse, extract, persist)])


async def run_document_workflow(data: bytes, filename: str, content_type: str, repository, storage_uri: str | None = None):
    document_id, version_id = str(uuid4()), str(uuid4())
    record = DocumentRecord(
        id=document_id,
        version_id=version_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_uri=storage_uri,
        status="processing",
        created_at=datetime.now(timezone.utc),
    )
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    app_name, user_id, session_id = "argus", "system", str(uuid4())
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    runner = Runner(
        app_name=app_name,
        node=build_document_workflow(repository),
        session_service=sessions,
    )
    result = None
    from google.genai import types

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="Process this document")]),
        invocation_id=session_id,
        state_delta={
            "data": data,
            "filename": filename,
            "content_type": content_type,
            "record": record,
            "document_id": document_id,
            "version_id": version_id,
        },
    ):
        if event.node_info.name == "persist_claims" and event.output is not None:
            result = event.output
    if result is None:
        raise RuntimeError("ADK document workflow produced no persistence result")
    result["document"] = DocumentRecord.model_validate(result["document"])
    result["claims"] = TypeAdapter(list[Claim]).validate_python(result["claims"])
    return result
