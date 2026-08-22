from __future__ import annotations

import os

from dotenv import load_dotenv
from google.cloud import vectorsearch_v1

from app.tools.vector_search import EmbeddingService


load_dotenv()


PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get(
    "AGENT_RETRIEVAL_LOCATION",
    "us-central1",
)
COLLECTION_ID = os.environ["AGENT_RETRIEVAL_COLLECTION_ID"]

VECTOR_FIELD = os.environ.get(
    "AGENT_RETRIEVAL_VECTOR_FIELD",
    "claim_embedding",
)

QUERY_TEXT = (
    "Algorithmic recommendation systems systematically increase "
    "political polarization by amplifying emotionally charged content."
)


def main() -> None:
    print("Generating query embedding...")

    embedding_service = EmbeddingService()

    query_embedding = embedding_service.embed_query(
        QUERY_TEXT
    )

    print(
        f"Query embedding dimensions: {len(query_embedding)}"
    )

    if len(query_embedding) != embedding_service.dimensions:
        raise RuntimeError(
            f"Expected {embedding_service.dimensions} dimensions, "
            f"got {len(query_embedding)}"
        )

    client = vectorsearch_v1.DataObjectSearchServiceClient()

    parent = (
        f"projects/{PROJECT_ID}"
        f"/locations/{LOCATION}"
        f"/collections/{COLLECTION_ID}"
    )

    vector_search = vectorsearch_v1.VectorSearch(
        search_field=VECTOR_FIELD,
        vector={
            "values": query_embedding,
        },
        top_k=5,
    )

    request = vectorsearch_v1.SearchDataObjectsRequest(
        parent=parent,
        vector_search=vector_search,
    )

    print()
    print("Searching Agent Retrieval...")
    print(f"Collection: {COLLECTION_ID}")
    print(f"Top K:      5")
    print()

    response = client.search_data_objects(
        request=request,
    )

    print("Search results")
    print("=" * 70)

    for index, result in enumerate(response.results, start=1):
        print(f"\nResult #{index}")
        print(result)


if __name__ == "__main__":
    main()