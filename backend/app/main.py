import os

# ADK/Google Cloud clients may create gRPC channels before a macOS child
# process is spawned.  Without gRPC's fork support, a failed/retried agent
# call can emit "FD from fork parent" warnings and terminate Python during
# cleanup.  This must be set before importing Google client modules.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "1")

import logging
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.tools.document_parser import UnsupportedDocumentType
from app.tools.firestore import FirestoreRepository
from app.tools.storage import CloudStorage
from app.workflows.document_workflow import run_document_workflow
from app.models.graph import ArgumentGraph
from app.tools.argument_graph import ArgumentGraphBuilder
from app.nodes.integrity import IntegrityInterceptor
from app.guardrails.local import LocalContentGuardrail
from app.guardrails.model_armor import ModelArmorContentGuardrail
from app.workflows.coaching_workflow import run_coaching_workflow
from app.models.issue import Issue, IssueEvent
from pydantic import BaseModel, model_validator


class CoachingRequest(BaseModel):
    user_prompt: str
    selected_claim_id: str | None = None
    selected_conflict_id: str | None = None
    selected_issue_id: str | None = None

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selected_claim_id and self.selected_conflict_id:
            raise ValueError(
                "Specify either selected_claim_id or selected_conflict_id, not both."
            )
        selections = [
            self.selected_claim_id,
            self.selected_conflict_id,
            self.selected_issue_id,
        ]
        if sum(selection is not None for selection in selections) > 1:
            raise ValueError("Specify only one claim, conflict, or issue selection.")
        return self


load_dotenv()

app = FastAPI(title="Argus API")

def _build_content_guardrail():
    if os.getenv("MODEL_ARMOR_ENABLED", "false").lower() == "true":
        return ModelArmorContentGuardrail()
    return LocalContentGuardrail()


content_guardrail = _build_content_guardrail()


@app.on_event("shutdown")
def close_firestore_client():
    FirestoreRepository.close_shared_client()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "argus-api",
    }


from app.tools.pubsub import (
    initialize_pubsub,
    PubSubBroker,
    decode_pubsub_push_body,
    on_document_uploaded,
    publish_document_uploaded_cloud,
)
from fastapi import status

# Initialize pubsub
initialize_pubsub()


@app.post("/documents/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    document_id: str | None = None,
    parent_version_id: str | None = None,
):
    """
    Upload a document, calculate its version sequence, publish 'document.uploaded'
    to Pub/Sub, and return 202 immediately to enable non-blocking UI polling.
    """
    filename = file.filename or "document"
    if filename.lower().rsplit(".", 1)[-1] not in {"pdf", "docx"}:
        raise HTTPException(status_code=415, detail="Only PDF and DOCX documents are supported")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    repo = FirestoreRepository()
    
    # Resolve or create document_id
    if not document_id:
        doc_id = str(uuid4())
        version_num = 1
    else:
        doc_id = document_id
        # Calculate next version number
        existing_versions = repo.get_document_versions(doc_id)
        version_num = len(existing_versions) + 1
        if not parent_version_id and existing_versions:
            # Default parent to last known version
            parent_version_id = existing_versions[-1].version_id

    version_id = str(uuid4())

    try:
        storage = CloudStorage()
        object_name = f"documents/{uuid4()}-{filename}"
        storage_uri = storage.upload(data, object_name, file.content_type or "application/octet-stream")
        
        # Publish the uploaded document event to trigger async background workflow
        if os.getenv("PUBSUB_DOCUMENT_UPLOADED_TOPIC"):
            publish_document_uploaded_cloud(
                document_id=doc_id,
                version_id=version_id,
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                storage_uri=storage_uri,
                version_number=version_num,
                parent_version_id=parent_version_id,
            )
        else:
            broker = PubSubBroker()
            broker.publish(
                "document.uploaded",
                document_id=doc_id,
                version_id=version_id,
                filename=filename,
                content_type=file.content_type or "application/octet-stream",
                data=data,
                storage_uri=storage_uri,
                version_number=version_num,
                parent_version_id=parent_version_id,
            )
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Document upload initialization failed")

    return {
        "id": doc_id,
        "version_id": version_id,
        "version_number": version_num,
        "parent_version_id": parent_version_id,
        "status": "processing",
    }


@app.post("/internal/pubsub/document-uploaded")
async def receive_document_uploaded_event(
    body: dict,
    request: Request,
):
    """Receive a Pub/Sub push event and process the GCS-backed document."""
    if os.getenv("ENVIRONMENT", "development") == "production":
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=403, detail="Forbidden")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token

            claims = id_token.verify_oauth2_token(
                authorization.removeprefix("Bearer "),
                google_requests.Request(),
                audience=os.environ["PUBSUB_PUSH_AUDIENCE"],
            )
            if claims.get("email") != os.environ["PUBSUB_PUSH_SERVICE_ACCOUNT"]:
                raise ValueError("Unexpected Pub/Sub identity")
        except Exception as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc
    try:
        event = decode_pubsub_push_body(body)
        await on_document_uploaded(data=None, **event)
        return {"status": "processed"}
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Pub/Sub document event failed: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Document event processing failed") from exc


@app.get("/documents")
async def list_documents():
    """Retrieve all ingested document records from Firestore."""
    try:
        repo = FirestoreRepository()
        documents = repo.list_documents()
        return {
            "documents": [
                doc.model_dump(mode="json")
                for doc in documents
            ]
        }
    except Exception as exc:
        logging.getLogger(__name__).exception("Socratic coaching workflow failed")
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Failed to retrieve documents") from exc


@app.get("/documents/{document_id}/graph", response_model=ArgumentGraph)
async def get_document_graph(document_id: str, version_id: str | None = None):
    """Retrieve claims and conflicts for the specified draft version (or active draft), then compute centrality and coordinates using ArgumentGraphBuilder."""
    try:
        repo = FirestoreRepository()
        
        doc = repo.get_document(document_id)
        if not doc:
            claims = repo.get_document_claims(document_id)
            if not claims:
                raise HTTPException(status_code=404, detail="Document not found")
            target_version_id = version_id
        else:
            target_version_id = version_id or doc.version_id

        if target_version_id:
            claims = repo.get_version_claims(document_id, target_version_id)
            if not claims:
                claims = repo.get_document_claims(document_id)
        else:
            claims = repo.get_document_claims(document_id)

        if not claims:
            return ArgumentGraph(nodes=[], edges=[])
            
        conflicts = repo.get_conflicts(document_id)
        
        builder = ArgumentGraphBuilder()
        graph = builder.build(claims=claims, conflicts=conflicts)
        return graph
    except HTTPException:
        raise
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Failed to load document graph") from exc


@app.post("/documents/{document_id}/coaching")
async def post_document_coaching(document_id: str, req: CoachingRequest):
    """
    Evaluates policy boundaries via IntegrityInterceptor, logging interceptions to Firestore,
    calculates adaptive style coaching weights, and runs the Socratic workflow.
    """
    repo = FirestoreRepository()
    doc = repo.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Step 1: Screen untrusted user input before any agent sees it.
    input_guardrail = await content_guardrail.inspect_input(req.user_prompt)
    if not input_guardrail.allowed:
        return {
            "status": "intercepted",
            "interception": {
                "id": None,
                "classification_reason": input_guardrail.reason,
                "category": input_guardrail.category,
            },
            "coaching_response": (
                "### 🛡️ Content Safety Refusal\n\n"
                "I could not process that request because it attempted to override "
                "Argus instructions or access protected system information. "
                "Please ask for analysis, questions, or feedback instead."
            ),
        }

    # Step 2: Preserve the Argus-specific integrity policy.
    interceptor = IntegrityInterceptor(repo)
    interception = await interceptor.analyze(req.user_prompt, document_id)

    if interception:
        return {
            "status": "intercepted",
            "interception": {
                "id": interception.id,
                "classification_reason": interception.classification_reason,
                "timestamp": interception.timestamp.isoformat(),
            },
            "coaching_response": (
                "### 🛡️ Integrity Interceptor Refusal\n\n"
                "**I'm here to serve as your reasoning partner, not your ghostwriter.**\n\n"
                "Under Argus integrity policies, I cannot draft paragraphs, write sections, "
                "or generate prose/source code on your behalf. Let's work together to refine your thinking instead!\n\n"
                "How about we explore one of these Socratic alternatives instead?\n"
                "- **Structural Outline**: *\"How should I logically outline the points of this section?\"*\n"
                "- **Core Premises**: *\"What core premises or assumptions must I establish to back my claim?\"*\n"
                "- **Evidentiary Needs**: *\"What empirical data or citations do I need to support this logic?\"*\n"
                "- **Counterarguments**: *\"What potential objections or conflicts might arise from this reasoning?\"*"
            ),
        }

    # Step 3: Assemble argument context
    context_text = ""
    coaching_claim_id = req.selected_claim_id
    if req.selected_issue_id:
        issue = next(
            (candidate for candidate in repo.get_issues(document_id)
             if candidate.id == req.selected_issue_id),
            None,
        )
        if issue:
            coaching_claim_id = issue.claim_id or coaching_claim_id
            context_text = (
                f"Focusing on tracked {issue.status.upper()} issue:\n"
                f"Issue type: {issue.issue_type}\n"
                f"Section: {issue.section}\n"
                f"Description: {issue.description}\n"
                f"Question: {issue.question_text}\n"
                f"First detected version: {issue.first_detected_version}\n"
                f"Last checked version: {issue.last_checked_version}\n"
                f"Escalation count: {issue.escalation_count}"
            )
        else:
            context_text = f"Tracked issue ID '{req.selected_issue_id}' not found."
    elif req.selected_claim_id:
        claim = repo.get_claim(document_id, req.selected_claim_id)
        if claim:
            context_text = (
                f"Focusing on Claim: '{claim.text}'\n"
                f"Evidence Cited: {', '.join(claim.evidence_cited or [])}\n"
                f"Confidence Level: {claim.confidence}\n"
                f"Open Questions: {', '.join(claim.open_questions or [])}"
            )
        else:
            context_text = f"Claim Context ID '{req.selected_claim_id}' not found."
    elif req.selected_conflict_id:
        conflicts = repo.get_conflicts(document_id)
        conflict = next((c for c in conflicts if c.id == req.selected_conflict_id), None)
        if conflict:
            context_text = (
                "Focusing on Contradiction:\n\n"
                f"Claim A:\n{conflict.claim_a_text}\n\n"
                f"Claim B:\n{conflict.claim_b_text}\n\n"
                f"Conflict Explanation:\n{conflict.explanation}\n\n"
                f"Severity: {conflict.severity}\n"
                f"Verification Confidence: {conflict.confidence}"
            )
        else:
            context_text = f"Conflict Context ID '{req.selected_conflict_id}' not found."
    else:
        context_text = "General Document Review (no specific claim or conflict selected)."

    # Step 4: Compute and inject adaptive coaching style weighting guidelines
    try:
        from app.tools.adaptive_coaching import calculate_coaching_weights, inject_adaptive_instructions
        weights = calculate_coaching_weights(repo, document_id)
        adaptive_text = inject_adaptive_instructions(weights)
        context_text += adaptive_text
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to calculate/inject adaptive weights: {e}")

    # Step 5: Run the ADK Socratic Coaching Workflow
    try:
        coaching_feedback = await run_coaching_workflow(req.user_prompt, context_text)

        # Screen generated content before persistence or returning it to the UI.
        generated_output = "\n".join(
            [
                coaching_feedback.coaching_feedback,
                coaching_feedback.evidence_findings or "",
                *coaching_feedback.socratic_questions,
                *coaching_feedback.evidence_suggestions,
                *coaching_feedback.logical_flaws,
            ]
        )
        output_guardrail = await content_guardrail.inspect_output(generated_output)
        if not output_guardrail.allowed:
            return {
                "status": "blocked",
                "interception": {
                    "id": None,
                    "classification_reason": output_guardrail.reason,
                    "category": output_guardrail.category,
                },
                "coaching_response": (
                    "I generated a response that did not meet Argus safety or "
                    "integrity requirements, so it was not returned. Please ask "
                    "for questions, evidence gaps, or logical analysis instead."
                ),
            }
        
        # Persist Socratic Issues and Events (deduplicating against existing questions for this claim)
        existing_issues = repo.get_issues(document_id)
        existing_questions = {
            i.question_text.strip().lower()
            for i in existing_issues
            if i.claim_id == coaching_claim_id and i.question_text
        }

        new_issues = []
        new_events = []
        version_id = doc.version_id

        # 1. Socratic Specialists Questions
        for q in (coaching_feedback.socratic_questions or []):
            if not q or q.strip().lower() in existing_questions:
                continue
            existing_questions.add(q.strip().lower())
            issue_id = f"issue-soc-{uuid4()}"
            issue = Issue(
                id=issue_id,
                document_id=document_id,
                version_id=version_id,
                claim_id=coaching_claim_id,
                section="Socratic Analysis",
                issue_type="socratic",
                description="Structural weakness or premise assumptions flagged by Socratic specialist.",
                question_text=q,
                question_type="socratic",
                status="open",
                first_detected_version=version_id,
                last_checked_version=version_id,
            )
            event = IssueEvent(
                id=f"event-{uuid4()}",
                issue_id=issue_id,
                version_id=version_id,
                previous_status=None,
                new_status="open",
                event_type="created",
                explanation="Socratic issue detected and logged during coaching analysis."
            )
            new_issues.append(issue)
            new_events.append(event)

        # 2. Evidence Specialists Gaps
        for sugg in (coaching_feedback.evidence_suggestions or []):
            if not sugg or sugg.strip().lower() in existing_questions:
                continue
            existing_questions.add(sugg.strip().lower())
            issue_id = f"issue-ev-{uuid4()}"
            issue = Issue(
                id=issue_id,
                document_id=document_id,
                version_id=version_id,
                claim_id=coaching_claim_id,
                section="Evidence Analysis",
                issue_type="evidence",
                description="Empirical citation or validation gap identified by Evidence specialist.",
                question_text=sugg,
                question_type="evidence",
                status="open",
                first_detected_version=version_id,
                last_checked_version=version_id,
            )
            event = IssueEvent(
                id=f"event-{uuid4()}",
                issue_id=issue_id,
                version_id=version_id,
                previous_status=None,
                new_status="open",
                event_type="created",
                explanation="Evidence gap and citation validation warning recorded."
            )
            new_issues.append(issue)
            new_events.append(event)

        # 3. Argument Specialists Logical flaws
        for flaw in (coaching_feedback.logical_flaws or []):
            if not flaw or flaw.strip().lower() in existing_questions:
                continue
            existing_questions.add(flaw.strip().lower())
            issue_id = f"issue-log-{uuid4()}"
            issue = Issue(
                id=issue_id,
                document_id=document_id,
                version_id=version_id,
                claim_id=coaching_claim_id,
                section="Logic Analysis",
                issue_type="logic",
                description="Logical fallacy or premise coherence flaw identified by Argument specialist.",
                question_text=flaw,
                question_type="logic",
                status="open",
                first_detected_version=version_id,
                last_checked_version=version_id,
            )
            event = IssueEvent(
                id=f"event-{uuid4()}",
                issue_id=issue_id,
                version_id=version_id,
                previous_status=None,
                new_status="open",
                event_type="created",
                explanation="Logical fallback or fallacy identified by coordinator."
            )
            new_issues.append(issue)
            new_events.append(event)

        if new_issues:
            repo.save_issues(document_id, new_issues)
            repo.save_issue_events(document_id, new_events)

        return {
            "status": "allowed",
            "interception": None,
            "coaching_response": coaching_feedback.coaching_feedback,
            "structured_coaching": coaching_feedback.model_dump(),
        }
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        logging.getLogger(__name__).exception("Socratic coaching workflow failed")
        raise HTTPException(status_code=500, detail="Failed to run Socratic coaching team") from exc


@app.get("/documents/{document_id}/versions")
async def get_document_versions(document_id: str):
    """Retrieve all saved versions of a document."""
    repo = FirestoreRepository()
    versions = repo.get_document_versions(document_id)
    return {"versions": [v.model_dump(mode="json") for v in versions]}


@app.get("/documents/{document_id}/versions/{version_id}/diff")
async def get_version_diff(document_id: str, version_id: str):
    """Generate paragraph-level differences for a specific version against its parent draft."""
    from app.tools.revision_intelligence import diff_paragraphs
    repo = FirestoreRepository()
    v2_doc = repo.get_document_version(document_id, version_id)
    if not v2_doc:
        raise HTTPException(status_code=404, detail="Version draft not found")
    if not v2_doc.parent_version_id:
        return {"changes": []}
    v1_doc = repo.get_document_version(document_id, v2_doc.parent_version_id)
    if not v1_doc or not v1_doc.raw_text or not v2_doc.raw_text:
        return {"changes": []}
    changes = diff_paragraphs(v1_doc.raw_text, v2_doc.raw_text)
    return {"changes": [c.model_dump(mode="json") for c in changes]}


@app.get("/documents/{document_id}/issues")
async def get_document_issues(document_id: str):
    """Retrieve all tracked issues and their status histories across revisions."""
    repo = FirestoreRepository()
    issues = repo.get_issues(document_id)
    return {"issues": [i.model_dump(mode="json") for i in issues]}


@app.get("/documents/{document_id}/issue_events")
async def get_document_issue_events(document_id: str):
    """Retrieve all tracked issue state transitions across drafts."""
    repo = FirestoreRepository()
    events = repo.get_issue_events(document_id)
    return {"issue_events": [e.model_dump(mode="json") for e in events]}
