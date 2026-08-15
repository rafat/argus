import os

from dotenv import load_dotenv
from google.cloud import firestore

load_dotenv()

project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
database_id = os.environ["FIRESTORE_DATABASE"]

db = firestore.Client(
    project=project_id,
    database=database_id,
)

doc_ref = db.collection("test").document("hello")

doc_ref.set({
    "message": "Hello Firestore",
    "source": "local-mac",
})

doc = doc_ref.get()

print(doc.to_dict())