from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

from app.models.claim import Claim
from app.tools.vector_search import VectorSearchService


load_dotenv()


OUTPUT_DIR = Path("tmp/agent_retrieval_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


CLAIM_ID = "argus-test-claim-001"

CLAIM_TEXT = (
    "Algorithmic recommendation systems systematically increase "
    "political polarization by amplifying emotionally charged content."
)


def main() -> None:
    claim = Claim(
        id=CLAIM_ID,
        document_id="argus-test-document",
        document_version="v1",
        chapter="Test Chapter",
        section="Test Section",
        text=CLAIM_TEXT,
        evidence_cited=[],
        confidence=0.95,
        status="supported",
        open_questions=[],
    )

    service = VectorSearchService()

    print("Generating Gemini embedding...")
    print(f"Model: {service.embeddings.model}")
    print(f"Dimensions requested: {service.embeddings.dimensions}")
    print()

    embedding = service.embed_claim(claim)

    print(f"Actual embedding dimensions: {len(embedding)}")

    if len(embedding) != service.embeddings.dimensions:
        raise RuntimeError(
            f"Expected {service.embeddings.dimensions} dimensions, "
            f"got {len(embedding)}"
        )

    data = {
        "claim_id": claim.id,
        "document_id": claim.document_id,
        "document_version": claim.document_version,
        "text": claim.text,
        "chapter": claim.chapter,
        "section": claim.section,
        "status": claim.status,
        "confidence": claim.confidence,
    }

    vectors = {
        "claim_embedding": {
            "dense": {
                "values": embedding,
            }
        }
    }

    data_path = OUTPUT_DIR / "data.json"
    vectors_path = OUTPUT_DIR / "vectors.json"

    data_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    vectors_path.write_text(
        json.dumps(vectors, indent=2),
        encoding="utf-8",
    )

    print()
    print("Successfully generated real Argus embedding.")
    print()
    print(f"Data file:    {data_path}")
    print(f"Vector file:  {vectors_path}")
    print(f"Claim ID:     {claim.id}")
    print(f"Dimensions:   {len(embedding)}")
    print()
    print("The files are ready for Agent Retrieval.")


if __name__ == "__main__":
    main()