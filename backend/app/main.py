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
