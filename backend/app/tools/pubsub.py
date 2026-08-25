import asyncio
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class PubSubBroker:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PubSubBroker, cls).__new__(cls, *args, **kwargs)
            cls._instance._subscribers = {}
        return cls._instance

    def subscribe(self, topic: str, callback: Callable[..., Coroutine[Any, Any, None]]):
        """Register an async callback subscriber on a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def publish(self, topic: str, **kwargs):
        """Publish an event asynchronously in the background loop."""
        logger.info(f"Publishing Event '{topic}'")
        if topic not in self._subscribers:
            return
        for callback in self._subscribers[topic]:
            asyncio.create_task(self._safe_execute(callback, topic, **kwargs))

    async def _safe_execute(self, callback, topic, **kwargs):
        try:
            await callback(**kwargs)
        except Exception as e:
            logger.error(f"Error executing callback on topic '{topic}': {e}", exc_info=True)


async def on_document_uploaded(
    document_id: str,
    version_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    storage_uri: str | None,
    version_number: int,
    parent_version_id: str | None,
):
    """
    Subscribes to 'document.uploaded'. Performs async document parsing,
    extraction, embedding, and conflict verification.
    """
    from app.tools.firestore import FirestoreRepository
    from app.workflows.document_workflow import run_document_workflow
    from app.models.document import DocumentRecord

    repo = FirestoreRepository()

    # Save DocumentRecord in processing status
    record = DocumentRecord(
        id=document_id,
        version_id=version_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_uri=storage_uri,
        status="processing",
        version_number=version_number,
        parent_version_id=parent_version_id,
    )

    record.progress = 5.0
    record.progress_message = "Parsing text and document structure..."
    repo.save_document(record)

    try:
        from app.tools.document_parser import parse_document
        chunks = parse_document(data, filename, document_id, version_id)
        raw_text = "\n\n".join(chunk.text for chunk in chunks)
        record.raw_text = raw_text
    except Exception as e:
        logger.error(f"Failed to parse document raw text: {e}")
        record.status = "failed"
        record.progress_message = f"Parsing failed: {e}"
        repo.save_document(record)
        return

    record.progress = 10.0
    record.progress_message = "Starting semantic claim extraction..."
    repo.save_document(record)

    try:
        # Run standard document extraction pipeline with API-aligned tracking IDs
        await run_document_workflow(
            data=data,
            filename=filename,
            content_type=content_type,
            repository=repo,
            storage_uri=storage_uri,
            document_id=document_id,
            version_id=version_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
        )

        # Force record update to processed
        record.status = "processed"
        record.progress = 100.0
        record.progress_message = "Processing complete!"
        repo.save_document(record)

        # Trigger revision and issue re-evaluation if parent exists
        if parent_version_id:
            broker = PubSubBroker()
            broker.publish(
                "revision.created",
                document_id=document_id,
                parent_version_id=parent_version_id,
                new_version_id=version_id,
            )
    except Exception as e:
        logger.error(f"Asynchronous document processing failed: {e}", exc_info=True)
        record.status = "failed"
        record.progress_message = f"Processing failed: {e}"
        repo.save_document(record)


async def on_revision_created(
    document_id: str,
    parent_version_id: str,
    new_version_id: str,
):
    """
    Subscribes to 'revision.created'. Diff-compares drafts, semantically Aligns
    claims, and processes/escalates revision issues.
    """
    from app.tools.firestore import FirestoreRepository
    from app.tools.revision_intelligence import diff_paragraphs, analyze_revision_issues

    repo = FirestoreRepository()

    v1_doc = repo.get_document_version(document_id, parent_version_id)
    v2_doc = repo.get_document_version(document_id, new_version_id)

    if not v1_doc or not v2_doc or not v1_doc.raw_text or not v2_doc.raw_text:
        logger.warning(f"Draft text not found for comparison matching V1={parent_version_id} or V2={new_version_id}")
        return

    # Compute paragraph level differences
    changes = diff_paragraphs(v1_doc.raw_text, v2_doc.raw_text)

    # Fetch V1 and V2 claims
    v1_claims = repo.get_version_claims(document_id, parent_version_id)
    v2_claims = repo.get_version_claims(document_id, new_version_id)

    # Process and evaluate issues
    await analyze_revision_issues(
        repo=repo,
        document_id=document_id,
        v1_version_id=parent_version_id,
        v2_version_id=new_version_id,
        v1_claims=v1_claims,
        v2_claims=v2_claims,
        changes=changes,
    )


# ---------------------------------------------------------------------------
# Pub/Sub Initialization & Registration
# ---------------------------------------------------------------------------

def initialize_pubsub():
    """Initializes and registers standard core listeners on topics."""
    broker = PubSubBroker()
    broker.subscribe("document.uploaded", on_document_uploaded)
    broker.subscribe("revision.created", on_revision_created)
    logger.info("Pub/Sub broker successfully initialized with core subscribers.")
