import asyncio
import base64
import json
import logging
import os
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


def publish_document_uploaded_cloud(
    *,
    document_id: str,
    version_id: str,
    filename: str,
    content_type: str,
    storage_uri: str,
    version_number: int,
    parent_version_id: str | None,
) -> str:
    """Publish a durable GCS-backed event for a Cloud Pub/Sub push subscription."""
    from google.cloud import pubsub_v1

    topic = os.environ["PUBSUB_DOCUMENT_UPLOADED_TOPIC"]
    publisher = pubsub_v1.PublisherClient()
    payload = {
        "document_id": document_id,
        "version_id": version_id,
        "filename": filename,
        "content_type": content_type,
        "storage_uri": storage_uri,
        "version_number": version_number,
        "parent_version_id": parent_version_id,
    }
    return publisher.publish(topic, json.dumps(payload).encode("utf-8")).result(timeout=30)


def decode_pubsub_push_body(body: dict[str, Any]) -> dict[str, Any]:
    """Decode and validate a standard Pub/Sub push envelope."""
    encoded = body.get("message", {}).get("data")
    if not encoded:
        raise ValueError("Pub/Sub push message has no data")
    event = json.loads(base64.b64decode(encoded).decode("utf-8"))
    required = {"document_id", "version_id", "filename", "storage_uri"}
    missing = required - event.keys()
    if missing:
        raise ValueError(f"Pub/Sub event missing fields: {sorted(missing)}")
    return event


async def on_document_uploaded(
    document_id: str,
    version_id: str,
    filename: str,
    content_type: str,
    data: bytes | None,
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

    if data is None:
        if not storage_uri or not storage_uri.startswith("gs://"):
            raise ValueError("A production event must contain a gs:// storage URI")
        from google.cloud import storage as gcs
        bucket_name, object_name = storage_uri.removeprefix("gs://").split("/", 1)
        data = gcs.Client().bucket(bucket_name).blob(object_name).download_as_bytes()

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

    # Extracted document text is untrusted data. It must pass a document
    # guardrail before it can reach any extraction agent instructions.
    from app.guardrails.local import LocalContentGuardrail
    document_guardrail = await LocalContentGuardrail().inspect_document(raw_text)
    if not document_guardrail.allowed:
        logger.warning(
            "Document blocked by content guardrail: document_id=%s category=%s",
            document_id,
            document_guardrail.category,
        )
        record.status = "blocked"
        record.progress = 100.0
        record.progress_message = "Processing stopped by document content safety policy."
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
        # Let a real Pub/Sub push request return non-2xx so the message is
        # retried. The local broker still catches and logs this exception.
        raise


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
