from __future__ import annotations

import os

from dotenv import load_dotenv
from google.cloud import aiplatform

load_dotenv()


PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("VECTOR_SEARCH_LOCATION", "us-central1")

INDEX_ID = os.environ["VECTOR_SEARCH_INDEX_ID"]
ENDPOINT_ID = os.environ["VECTOR_SEARCH_ENDPOINT_ID"]

DEPLOYED_INDEX_ID = os.environ.get(
    "VECTOR_SEARCH_DEPLOYED_INDEX_ID",
    "argus_claims_v1",
)


def main() -> None:
    aiplatform.init(
        project=PROJECT_ID,
        location=LOCATION,
    )

    index = aiplatform.MatchingEngineIndex(
        index_name=INDEX_ID,
        project=PROJECT_ID,
        location=LOCATION,
    )

    endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=ENDPOINT_ID,
        project=PROJECT_ID,
        location=LOCATION,
    )

    print("Deploying Vector Search index...")
    print("Index:", INDEX_ID)
    print("Endpoint:", ENDPOINT_ID)
    print("Deployed ID:", DEPLOYED_INDEX_ID)

    endpoint.deploy_index(
        index=index,
        deployed_index_id=DEPLOYED_INDEX_ID,
        min_replica_count=1,
        max_replica_count=1,
        sync=True,
    )

    print()
    print("Vector Search index deployed successfully.")
    print("Endpoint:", endpoint.resource_name)
    print("Deployed index ID:", DEPLOYED_INDEX_ID)


if __name__ == "__main__":
    main()