import pytest
from pathlib import Path

from app.models.claim import Claim
from app.models.document import DocumentRecord
from app.tools.firestore import FirestoreRepository
from app.workflows.document_workflow import run_document_workflow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_document_workflow():
    path = Path(__file__).parent / "argus_test.docx"

    repository = FirestoreRepository()


    result = await run_document_workflow(
        data=path.read_bytes(),
        filename="argus_test.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        repository=repository,
    )

    assert "document" in result
    assert "claims" in result

    record = result["document"]
    claims = result["claims"]

    assert isinstance(record, DocumentRecord)
    assert record.status == "processed"

    assert isinstance(claims, list)
    assert len(claims) > 0
    assert all(isinstance(claim, Claim) for claim in claims)

    print("\nDocument:")
    print(record)

    print("\nClaims:")
    for claim in claims:
        print(f"- {claim.text}")
        print(f"  Chapter: {claim.chapter}")
        print(f"  Section: {claim.section}")
        print(f"  Confidence: {claim.confidence}")