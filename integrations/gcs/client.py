"""Google Cloud Storage: upload a rendered video and hand back a URL other services can fetch.

Auth: Application Default Credentials (`gcloud auth application-default login`) or a service-account
key at GOOGLE_APPLICATION_CREDENTIALS. Signed URLs need the service-account key; public URLs work
with either as long as the bucket allows public reads (this client can set that up).
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import requests


class GCSError(RuntimeError):
    pass


class GCSClient:
    def __init__(self, bucket: str, project: str | None = None):
        if not bucket:
            raise GCSError("No bucket configured: set [gcs] bucket in pipeline.toml")
        try:
            from google.cloud import storage
        except ImportError as e:
            raise GCSError("google-cloud-storage is not installed (uv sync)") from e
        self.bucket_name = bucket
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT") or None
        # A service-account key in .env (GOOGLE_APPLICATION_CREDENTIALS) may be a project-relative path.
        key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if key and not os.path.isabs(key):
            from integrations.config import PROJECT_ROOT
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(PROJECT_ROOT / key)
        if key and not os.path.exists(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]):
            raise GCSError(f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {key}")
        try:
            self.client = storage.Client(project=self.project)
        except Exception as e:  # DefaultCredentialsError etc.
            raise GCSError(f"Google credentials not available: {e}. Run `gcloud auth application-default login`.") from e

    # ---------------------------------------------------------------- bucket
    def ensure_bucket(self, location: str = "US", public: bool = True):
        from google.api_core.exceptions import Forbidden, NotFound
        from google.auth.exceptions import RefreshError
        try:
            bucket = self.client.lookup_bucket(self.bucket_name)
            created = False
            if bucket is None:
                bucket = self.client.create_bucket(self.bucket_name, location=location, project=self.project)
                created = True
            if public:
                policy = bucket.get_iam_policy(requested_policy_version=3)
                binding = next((b for b in policy.bindings if b["role"] == "roles/storage.objectViewer"), None)
                if not binding or "allUsers" not in binding["members"]:
                    policy.bindings.append({"role": "roles/storage.objectViewer", "members": {"allUsers"}})
                    bucket.set_iam_policy(policy)
            return bucket, created
        except RefreshError as e:
            raise GCSError(f"Google credentials expired: {e}. Run `gcloud auth application-default login`.") from e
        except (Forbidden, NotFound) as e:
            raise GCSError(f"Bucket access problem for '{self.bucket_name}': {e}") from e

    # ---------------------------------------------------------------- objects
    def upload(self, local_path: str | Path, object_name: str, content_type: str = "video/mp4") -> dict:
        from google.auth.exceptions import RefreshError
        local_path = Path(local_path)
        if not local_path.exists():
            raise GCSError(f"file not found: {local_path}")
        try:
            blob = self.client.bucket(self.bucket_name).blob(object_name)
            blob.upload_from_filename(str(local_path), content_type=content_type)
            blob.reload()
        except RefreshError as e:
            raise GCSError(f"Google credentials expired: {e}. Run `gcloud auth application-default login`.") from e
        return {
            "bucket": self.bucket_name,
            "object": object_name,
            "size": blob.size,
            "md5": blob.md5_hash,
            "gs_uri": f"gs://{self.bucket_name}/{object_name}",
            "public_url": self.public_url(object_name),
        }

    def public_url(self, object_name: str) -> str:
        return f"https://storage.googleapis.com/{self.bucket_name}/{object_name}"

    def signed_url(self, object_name: str, days: int = 7) -> str:
        blob = self.client.bucket(self.bucket_name).blob(object_name)
        try:
            return blob.generate_signed_url(version="v4", expiration=timedelta(days=days), method="GET")
        except Exception as e:
            raise GCSError(f"Signed URLs need a service-account key (GOOGLE_APPLICATION_CREDENTIALS): {e}") from e

    @staticmethod
    def verify_url(url: str, timeout: int = 20) -> tuple[int, int | None, str | None]:
        """HEAD the URL the way Metricool would. Returns (status, content_length, content_type)."""
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        cl = r.headers.get("Content-Length")
        return r.status_code, (int(cl) if cl else None), r.headers.get("Content-Type")
