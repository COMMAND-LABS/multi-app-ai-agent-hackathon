---
name: gcs
description: Upload rendered videos to Google Cloud Storage and get a public URL (step 6). Use for any "upload / store the video / get a link" request or when Metricool needs a media URL.
---

# Google Cloud Storage

```bash
uv run python -m integrations.gcs.upload [--run-id X] [--brief-id ID] [--file path] [--dry-run]
```

- Auth: Application Default Credentials (`gcloud auth application-default login`), or a service-account
  key at `GOOGLE_APPLICATION_CREDENTIALS` in `.env`. A `RefreshError` / "credentials expired" means
  the user must re-run `gcloud auth login` and `gcloud auth application-default login` — you cannot.
- Bucket, prefix, location and URL mode come from `pipeline.toml` `[gcs]`. The bucket is created on
  first use; in `public` mode it gets an `allUsers: objectViewer` IAM binding so Metricool can fetch
  the file. `signed` mode needs a service-account key.
- Object path: `<prefix>/<run_id>/<brief_id>.mp4`. After upload the step HEADs the URL and records
  `gcs_verified` in `reports/<run_id>/deliverables.json`; receipt in `gcs_upload.md`.
- `--dry-run` computes the URL and writes the receipt without touching the cloud; `evaluate` then
  reports "dry run only" instead of failing.
