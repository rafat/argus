from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from app.tools.firestore import FirestoreRepository
from app.workflows.document_workflow import DocumentWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Argus claims from a PDF or DOCX")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    load_dotenv()
    data = args.path.read_bytes()
    record, claims = DocumentWorkflow(repository=FirestoreRepository()).run(
        data, args.path.name, "application/octet-stream"
    )
    print(json.dumps({"document": record.model_dump(mode="json"), "claims": [c.model_dump(mode="json") for c in claims]}, indent=2))


if __name__ == "__main__":
    main()
