from __future__ import annotations

import os

from dotenv import load_dotenv
from google.cloud import aiplatform

load_dotenv()


PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("VECTOR_SEARCH_LOCATION", "us-central1")
DISPLAY_NAME = os.environ.get(
    "VECTOR_SEARCH_ENDPOINT_NAME",
    "argus-claims-endpoint",
)


def main() -> None:
    aiplatform.init(
        project=PROJECT_ID,
        location=LOCATION,
    )

    print("Creating Vector Search endpoint...")
    print(f"Project:  {PROJECT_ID}")
    print(f"Location: {LOCATION}")
    print(f"Name:     {DISPLAY_NAME}")

    endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
        display_name=DISPLAY_NAME,
        public_endpoint_enabled=True,
        description=(
            "Argus claim retrieval endpoint."
        ),
        sync=True,
    )

    print()
    print("Vector Search endpoint created.")
    print("Display name:", endpoint.display_name)
    print("Resource name:", endpoint.resource_name)
    print("Endpoint ID:", endpoint.name.split("/")[-1])


if __name__ == "__main__":
    main()