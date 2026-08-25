from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)
from uuid import uuid4

from google.adk.workflow import FunctionNode, START, Workflow
from google.adk.workflow import RetryConfig

from app.agents.extraction import build_extraction_agent, extract_claim_drafts_sync
from app.models.claim import Claim, ClaimDraft
from app.models.document import DocumentRecord
from app.nodes.parsing import parse_upload
from app.nodes.persistence import persist_result
from app.nodes.validation import request_correction, validate_claims

from app.tools.vector_search import VectorSearchService
from app.nodes.retrieval_index import index_claims
from app.nodes.conflict_analysis import analyze_conflicts
from app.nodes.conflict_persistence import persist_conflicts


def _materialize_claims(
    node_input,
    chunk: dict,
) -> list[Claim]:
    drafts = TypeAdapter(
        list[ClaimDraft]
    ).validate_python(node_input)

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
        func=lambda ctx, node_input: _seed_chunk(
            ctx,
            node_input,
        ),
        name="seed_chunk",
    )

    extraction = build_extraction_agent()

    extraction.retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=2.0,
        jitter=1.0,
    )

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
            (
                START,
                seed,
                extraction,
                validation,
            ),
            (
                validation,
                {
                    "valid": _chunk_result_node(),
                    "invalid": correction,
                },
            ),
            (
                correction,
                extraction,
            ),
        ],
    )


def _return_drafts(
    node_input: list[ClaimDraft],
) -> list[ClaimDraft]:
    return node_input


def _chunk_result_node() -> FunctionNode:
    result = FunctionNode(
        func=_return_drafts,
        name="chunk_result",
    )

    result.input_schema = list[ClaimDraft]
    result.output_schema = list[ClaimDraft]

    return result


def _seed_chunk(
    ctx,
    node_input: dict,
) -> dict:
    ctx.state["chapter"] = node_input.get(
        "chapter",
        "",
    )

    ctx.state["section"] = node_input.get(
        "section",
        "",
    )

    ctx.state["chunk_text"] = node_input["text"]

    ctx.state["correction"] = ""

    ctx.state["chunk"] = node_input

    return {}


def build_document_workflow(repository) -> Workflow:
    """
    Build the ADK document graph.

    Pipeline:

        parse
          ↓
        extract
          ↓
        generate_embeddings
          ↓
        persist_claims
          ↓
        index_claims

    Firestore is the canonical claim store.
    Agent Retrieval is the semantic retrieval projection.
    """

    def _update_progress(node_input: dict, progress: float, message: str):
        try:
            record_data = node_input.get("record")
            if not record_data:
                return
            if isinstance(record_data, dict):
                doc_id = record_data.get("id")
            else:
                doc_id = getattr(record_data, "id", None)
            if doc_id:
                repository.update_document_progress(doc_id, progress, message)
        except Exception as ex:
            logger.warning(f"Failed to update progress: {ex}")

    # ---------------------------------------------------------
    # 1. Parse document
    # ---------------------------------------------------------

    parse = FunctionNode(
        func=parse_upload,
        name="parse_document",
    )

    # ---------------------------------------------------------
    # 2. Extract claims from all chunks
    # ---------------------------------------------------------

    async def extract_all(
        ctx,
        node_input: dict,
    ) -> dict:
        chunks = node_input["chunks"]
        total_chunks = len(chunks)
        logger.info(f"--- [ADK Workflow] Starting claim extraction across {total_chunks} chunks ---")
        _update_progress(node_input, 15.0, "Extracting claims...")

        claims: list[Claim] = []
        chunk_workflow = build_chunk_workflow()

        for i, chunk in enumerate(chunks, 1):
            chunk_data = chunk.model_dump()
            logger.info(f"    -> Extracting chunk {i} of {total_chunks} (Chapter: {chunk_data.get('chapter', 'N/A')}, Section: {chunk_data.get('section', 'N/A')})...")
            chunk_progress = 15.0 + (i / total_chunks) * 25.0
            _update_progress(node_input, chunk_progress, f"Extracting claims (chunk {i} of {total_chunks})...")

            # The GenAI client can otherwise retry an unavailable OAuth/API
            # endpoint for a long time, leaving the document permanently in
            # "processing".  Bound each chunk so the async worker records a
            # useful failure and the UI can stop polling.
            timeout_seconds = float(
                os.environ.get("ARGUS_AGENT_TIMEOUT_SECONDS", "120")
            )
            try:
                async with asyncio.timeout(timeout_seconds):
                    # The synchronous Vertex client avoids the ADK 2.5
                    # AsyncModels/AFC + gRPC fork issue observed on macOS.
                    # Set ARGUS_USE_ASYNC_GEMINI=true to force the original
                    # ADK path when running in an environment where it is
                    # known to be stable.
                    use_async_gemini = os.environ.get(
                        "ARGUS_USE_ASYNC_GEMINI", "false"
                    ).lower() in {"1", "true", "yes"}
                    if use_async_gemini:
                        drafts = await ctx.run_node(
                            chunk_workflow,
                            node_input=chunk_data,
                        )
                    else:
                        drafts = await asyncio.to_thread(
                            extract_claim_drafts_sync,
                            chunk_data,
                        )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Claim extraction timed out after {timeout_seconds:g} "
                    "seconds; check Google authentication and network access"
                ) from exc

            chunk_claims = _materialize_claims(
                drafts,
                chunk_data,
            )
            claims.extend(chunk_claims)
            logger.info(f"    -> Chunk {i} complete. Extracted {len(chunk_claims)} claims.")

        logger.info(f"--- [ADK Workflow] Claim extraction complete. Total claims extracted: {len(claims)} ---")
        return {
            "record": node_input["record"],
            "claims": claims,
        }

    extract = FunctionNode(
        func=extract_all,
        name="extract_chunks",
        rerun_on_resume=True,
    )

    extract.output_schema = dict

    # ---------------------------------------------------------
    # 3. Generate Gemini embeddings
    # ---------------------------------------------------------

    async def generate_embeddings(
        ctx,
        node_input: dict,
    ) -> dict:
        claims = TypeAdapter(
            list[Claim]
        ).validate_python(
            node_input["claims"]
        )
        total_claims = len(claims)
        logger.info(f"--- [ADK Workflow] Generating embeddings for {total_claims} claims ---")
        _update_progress(node_input, 45.0, "Generating high-dimensional semantic vectors...")

        vector_service = VectorSearchService()

        for idx, claim in enumerate(claims, 1):
            if idx % 5 == 1 or idx == total_claims:
                logger.info(f"    -> Embedding claim {idx} of {total_claims}...")
            embed_progress = 45.0 + (idx / total_claims) * 15.0
            _update_progress(node_input, embed_progress, f"Generating embeddings (claim {idx} of {total_claims})...")
            claim.embedding = (
                vector_service.embed_claim(claim)
            )

        logger.info("--- [ADK Workflow] Embedding generation complete ---")
        return {
            "record": node_input["record"],
            "claims": claims,
        }

    embed = FunctionNode(
        func=generate_embeddings,
        name="generate_embeddings",
    )

    embed.output_schema = dict

    # ---------------------------------------------------------
    # 4. Persist canonical claims to Firestore
    # ---------------------------------------------------------

    async def persist_claims(ctx, node_input: dict) -> dict:
        logger.info("--- [ADK Workflow] Persisting canonical claims and updating DocumentRecord in Firestore ---")
        _update_progress(node_input, 62.0, "Persisting extracted claims to Firestore database...")
        result = persist_result(
            node_input,
            repository,
        )
        logger.info("--- [ADK Workflow] Canonical claims successfully persisted to Firestore ---")

        return {
            "record": result["record"],
            "claims": result["claims"],
        }

    persist = FunctionNode(
        func=persist_claims,
        name="persist_claims",
    )

    persist.input_schema = dict
    persist.output_schema = dict

    # ---------------------------------------------------------
    # 5. Index claims in Agent Retrieval
    # ---------------------------------------------------------

    async def index_claims_wrapper(ctx, node_input: dict) -> dict:
        _update_progress(node_input, 65.0, "Indexing claims in Google Vector Search...")
        result = await index_claims(ctx, node_input)
        _update_progress(node_input, 80.0, "Claims indexing completed.")
        return result

    index = FunctionNode(
        func=index_claims_wrapper,
        name="index_claims",
    )
    index.output_schema = dict

    async def analyze_conflicts_wrapper(ctx, node_input: dict) -> dict:
        _update_progress(node_input, 82.0, "Starting contradiction candidate pairing...")
        result = await analyze_conflicts(ctx, node_input)
        return result

    conflict_analysis = FunctionNode(
        func=analyze_conflicts_wrapper,
        name="analyze_conflicts",
    )
    conflict_analysis.output_schema = dict

    def persist_conflicts_wrapper(node_input: dict) -> dict:
        _update_progress(node_input, 95.0, "Saving verified contradiction links to Firestore...")
        result = persist_conflicts(
            node_input,
            repository,
        )
        return result

    conflict_persist = FunctionNode(
        func=persist_conflicts_wrapper,
        name="persist_conflicts",
    )
    conflict_persist.input_schema = dict
    conflict_persist.output_schema = dict

    # ---------------------------------------------------------
    # Workflow graph
    # ---------------------------------------------------------

    return Workflow(
        name="document_workflow",
        edges=[
            (
                START,
                parse,
                extract,
                embed,
                persist,
                index,
                conflict_analysis,
                conflict_persist,
            )
        ],
    )


async def run_document_workflow(
    data: bytes,
    filename: str,
    content_type: str,
    repository,
    storage_uri: str | None = None,
    document_id: str | None = None,
    version_id: str | None = None,
    version_number: int = 1,
    parent_version_id: str | None = None,
):
    if not document_id:
        document_id = str(uuid4())
    if not version_id:
        version_id = str(uuid4())

    record = DocumentRecord(
        id=document_id,
        version_id=version_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_uri=storage_uri,
        status="processing",
        created_at=datetime.now(timezone.utc),
        version_number=version_number,
        parent_version_id=parent_version_id,
    )

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    app_name = "argus"
    user_id = "system"
    session_id = str(uuid4())

    sessions = InMemorySessionService()

    await sessions.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

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
        new_message=types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text="Process this document"
                )
            ],
        ),
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

        # The workflow now continues past indexing through contradiction
        # analysis and conflict persistence.  Waiting for index_claims here
        # made the runner discard the terminal output and report a successful
        # pipeline as failed.
        node_name = getattr(getattr(event, "node_info", None), "name", None)
        if node_name == "persist_conflicts" and event.output is not None:
            result = event.output

    if result is None:
        raise RuntimeError(
            "ADK document workflow produced no "
            "conflict persistence result"
        )

    result["document"] = DocumentRecord.model_validate(
        result["record"]
    )

    result["claims"] = TypeAdapter(
        list[Claim]
    ).validate_python(
        result["claims"]
    )

    return result
