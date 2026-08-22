import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.tools.document_parser import UnsupportedDocumentType
from app.tools.firestore import FirestoreRepository
from app.tools.storage import CloudStorage
from app.workflows.document_workflow import run_document_workflow

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


@app.get("/documents/{document_id}/graph")
async def get_document_graph(document_id: str):
    """Retrieve claims and conflicts, then compute centrality and coordinates via NetworkX."""
    try:
        import networkx as nx
        repo = FirestoreRepository()
        
        claims = repo.get_claims(document_id)
        if not claims:
            doc = repo.get_document(document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            return {"nodes": [], "edges": []}
            
        conflicts = repo.get_conflicts(document_id)
        
        # Build NetworkX directed graph
        G = nx.DiGraph()
        for claim in claims:
            G.add_node(claim.id)
        for conflict in conflicts:
            G.add_edge(conflict.claim_a_id, conflict.claim_b_id)
            
        # Calculate centrality (Degree Centrality is fast and standard)
        centrality_scores = nx.degree_centrality(G) if len(G) > 1 else {c.id: 1.0 for c in claims}
        
        # Calculate layout positions using spring_layout
        pos = nx.spring_layout(G, k=1.5, seed=42) if len(G) > 1 else {c.id: [0.0, 0.0] for c in claims}
        
        nodes = []
        for claim in claims:
            node_id = claim.id
            coords = pos[node_id]
            nodes.append({
                "id": node_id,
                "type": "claimNode",
                "position": {"x": float(coords[0] * 600), "y": float(coords[1] * 600)},
                "data": {
                    "text": claim.text,
                    "chapter": claim.chapter,
                    "section": claim.section,
                    "status": claim.status,
                    "confidence": claim.confidence,
                    "centrality": float(centrality_scores.get(node_id, 0.5)),
                    "open_questions": claim.open_questions,
                    "evidence_cited": claim.evidence_cited,
                }
            })
            
        edges = []
        for conflict in conflicts:
            edges.append({
                "id": conflict.id,
                "source": conflict.claim_a_id,
                "target": conflict.claim_b_id,
                "type": "conflictEdge",
                "animated": conflict.severity == "high",
                "data": {
                    "explanation": conflict.explanation,
                    "severity": conflict.severity,
                    "confidence": conflict.confidence,
                }
            })
            
        return {
            "nodes": nodes,
            "edges": edges,
        }
    except HTTPException:
        raise
    except Exception as exc:
        if os.environ.get("ENVIRONMENT", "development") == "development":
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Failed to load document graph") from exc

