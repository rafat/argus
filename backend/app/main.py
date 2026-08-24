import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.tools.document_parser import UnsupportedDocumentType
from app.tools.firestore import FirestoreRepository
from app.tools.storage import CloudStorage
from app.workflows.document_workflow import run_document_workflow
from app.models.graph import ArgumentGraph
from app.tools.argument_graph import ArgumentGraphBuilder
from app.nodes.integrity import IntegrityInterceptor
from app.workflows.coaching_workflow import run_coaching_workflow
from pydantic import BaseModel, model_validator


class CoachingRequest(BaseModel):
    user_prompt: str
    selected_claim_id: str | None = None
    selected_conflict_id: str | None = None

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selected_claim_id and self.selected_conflict_id:
            raise ValueError(
                "Specify either selected_claim_id or selected_conflict_id, not both."
            )
        return self


load_dotenv()

app = FastAPI(title="Argus API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
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


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and synchronously run the Day 2 extraction workflow."""
    filename = file.filename or "document"
    if filename.lower().rsplit(".", 1)[-1] not in {"pdf", "docx"}:
        raise HTTPException(status_code=415, detail="Only PDF and DOCX documents are supported")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    try:
        storage = CloudStorage()
        object_name = f"documents/{uuid4()}-{filename}"
        storage_uri = storage.upload(data, object_name, file.content_type or "application/octet-stream")
        result = await run_document_workflow(
            data=data,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            repository=FirestoreRepository(),
            storage_uri=storage_uri,
        )
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Document processing failed") from exc

    return {
        "document": result["document"].model_dump(mode="json"),
        "claims": [claim.model_dump(mode="json") for claim in result["claims"]],
    }


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
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Failed to retrieve documents") from exc


@app.get("/documents/{document_id}/graph", response_model=ArgumentGraph)
async def get_document_graph(document_id: str):
    """Retrieve claims and conflicts, then compute centrality and coordinates using ArgumentGraphBuilder."""
    try:
        repo = FirestoreRepository()
        
        claims = repo.get_document_claims(document_id)
        if not claims:
            doc = repo.get_document(document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
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
    and runs the collaborative ADK 2.x Socratic coaching workflow if cleared.
    """
    repo = FirestoreRepository()
    doc = repo.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Step 1: Enforce Integrity Interceptor
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

    # Step 2: Assemble argument context
    context_text = ""
    if req.selected_claim_id:
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

    # Step 3: Run the ADK Socratic Coaching Workflow
    try:
        coaching_feedback = await run_coaching_workflow(req.user_prompt, context_text)
        return {
            "status": "allowed",
            "interception": None,
            "coaching_response": coaching_feedback.coaching_feedback,
            "structured_coaching": coaching_feedback.model_dump(),
        }
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Failed to run Socratic coaching team") from exc


