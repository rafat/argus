from __future__ import annotations

import os

from dotenv import load_dotenv
from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_config import (
    DistanceMeasureType,
)

load_dotenv()


PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get(
    "VECTOR_SEARCH_LOCATION",
    "us-central1",
)
DISPLAY_NAME = os.environ.get(
    "VECTOR_SEARCH_INDEX_NAME",
    "argus-claims-index",
)

EMBEDDING_DIMENSIONS = int(
    os.environ.get(
        "EMBEDDING_DIMENSIONS",
        "3072",
    )
)


def main() -> None:
    aiplatform.init(
        project=PROJECT_ID,
        location=LOCATION,
    )

    print("Creating Argus Vector Search index...")
    print(f"Project:             {PROJECT_ID}")
    print(f"Location:            {LOCATION}")
    print(f"Display name:        {DISPLAY_NAME}")
    print(f"Dimensions:          {EMBEDDING_DIMENSIONS}")
    print("Distance measure:    DOT_PRODUCT_DISTANCE")
    print("Update method:       STREAM_UPDATE")
    print("Shard size:          SHARD_SIZE_SMALL")
    print("Algorithm:           Tree-AH")
    print()

    index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
        display_name=DISPLAY_NAME,

        # Must match the dimensionality produced by
        # gemini-embedding-001.
        dimensions=EMBEDDING_DIMENSIONS,

        # Number of approximate nearest neighbors considered
        # during retrieval.
        approximate_neighbors_count=100,

        # Tree-AH configuration.
        leaf_node_embedding_count=500,
        leaf_nodes_to_search_percent=7,

        # Argus uses semantic similarity for candidate retrieval.
        distance_measure_type=(
            DistanceMeasureType.DOT_PRODUCT_DISTANCE
        ),

        # Claims will be added continuously as documents are processed.
        index_update_method="STREAM_UPDATE",

        # Explicitly use the smallest shard size appropriate
        # for the Argus MVP/development workload.
        shard_size="SHARD_SIZE_SMALL",

        description=(
            "Argus claim embeddings for semantic candidate "
            "retrieval and contradiction analysis."
        ),

        # Wait until the index creation operation completes.
        sync=True,
    )

    index_id = index.name.split("/")[-1]

    print()
    print("=" * 60)
    print("Vector Search index created successfully")
    print("=" * 60)
    print(f"Display name: {index.display_name}")
    print(f"Resource name: {index.resource_name}")
    print(f"Index ID:      {index_id}")
    print()
    print("Add this to your .env:")
    print()
    print(f"VECTOR_SEARCH_INDEX_ID={index_id}")
    print()


if __name__ == "__main__":
    main()