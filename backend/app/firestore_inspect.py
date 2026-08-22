import os

from google.cloud import firestore


client = firestore.Client(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    database=os.environ["FIRESTORE_DATABASE"],
)

documents = client.collection("documents").stream()

for doc in documents:
    print(f"\nDOCUMENT: {doc.id}")
    print(doc.to_dict())

    claims = (
        client.collection("documents")
        .document(doc.id)
        .collection("claims")
        .stream()
    )

    print("CLAIMS:")

    for claim in claims:
        print(f"\n  {claim.id}")
        print(claim.to_dict())