from __future__ import annotations

import os


class CloudStorage:
    def __init__(self, bucket_name: str | None = None, client=None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET")
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET is required for document storage")
        if client is None:
            from google.cloud import storage

            client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.bucket = client.bucket(self.bucket_name)

    def upload(self, data: bytes, object_name: str, content_type: str) -> str:
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{object_name}"
