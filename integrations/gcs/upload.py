"""Step 6: upload a finished video to Google Cloud Storage and record its URL.

    uv run python -m integrations.gcs.upload [--run-id X] [--brief-id ID] [--file path] [--dry-run]

Finds <agent_dir>/output/<brief_id>/video.mp4 (or --file), uploads it to
gs://<bucket>/<prefix>/<run_id>/<brief_id>.mp4, verifies the URL answers a HEAD request, and records
the result in reports/<run_id>/deliverables.json (one entry per brief) and gcs_upload.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from analysis import config as pipeline_config
from analysis import progress
from analysis.run import current_run_id, rel, report_dir
from integrations.config import PROJECT_ROOT
from integrations.gcs import GCSClient, GCSError


def deliverables_path(folder: Path) -> Path:
    return folder / "deliverables.json"


def load_deliverables(folder: Path) -> dict:
    p = deliverables_path(folder)
    return json.loads(p.read_text()) if p.exists() else {"run_id": folder.name, "briefs": {}}


def save_deliverables(folder: Path, data: dict) -> None:
    deliverables_path(folder).write_text(json.dumps(data, indent=2) + "\n")


def find_briefs(run_id: str, agent_dir: Path) -> list[str]:
    out = agent_dir / "output"
    return sorted(p.name for p in out.glob(f"{run_id}__*") if (p / "video.mp4").exists()) if out.exists() else []


def main(argv: list[str] | None = None) -> int:
    cfg = pipeline_config.section("gcs")
    vcfg = pipeline_config.section("video")
    p = argparse.ArgumentParser(prog="python -m integrations.gcs.upload", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id")
    p.add_argument("--brief-id", help="e.g. <run_id>__<video_id>; default: every finished brief of the run")
    p.add_argument("--file", help="upload this file instead of the agent's output")
    p.add_argument("--bucket", default=cfg["bucket"])
    p.add_argument("--dry-run", action="store_true", help="compute names, touch nothing in the cloud")
    args = p.parse_args(argv)
    run_id = args.run_id or current_run_id()
    folder = report_dir(run_id)
    agent_dir = (PROJECT_ROOT / vcfg["agent_dir"]).resolve()

    brief_ids = [args.brief_id] if args.brief_id else find_briefs(run_id, agent_dir)
    if not brief_ids:
        sys.exit(f"No finished videos for run {run_id} under {agent_dir}/output/")
    deliverables = load_deliverables(folder)
    progress.log("gcs", f"uploading {len(brief_ids)} video(s) to gs://{args.bucket}/{cfg['prefix']}", run_id)

    client = None
    if not args.dry_run:
        try:
            client = GCSClient(args.bucket, project=cfg.get("project") or None)
            _, created = client.ensure_bucket(location=cfg["location"], public=(cfg["url_mode"] == "public"))
            if created:
                progress.log("gcs", f"created bucket {args.bucket} ({cfg['location']}, public={cfg['url_mode'] == 'public'})", run_id)
        except GCSError as e:
            progress.log("gcs", f"FAILED: {e}", run_id)
            print(f"error: {e}", file=sys.stderr)
            return 1

    rows = []
    for bid in brief_ids:
        src = Path(args.file) if args.file else agent_dir / "output" / bid / "video.mp4"
        obj = f"{cfg['prefix'].strip('/')}/{run_id}/{bid}.mp4"
        entry = deliverables["briefs"].setdefault(bid, {})
        entry.update({"video_path": str(src), "gcs_object": obj})
        if args.dry_run:
            entry["gcs_url"] = f"https://storage.googleapis.com/{args.bucket}/{obj}"
            rows.append((bid, "dry-run", entry["gcs_url"], "-"))
            continue
        try:
            info = client.upload(src, obj)
            url = client.signed_url(obj, cfg["signed_url_days"]) if cfg["url_mode"] == "signed" else info["public_url"]
            status, size, ctype = client.verify_url(url)
            ok = status == 200 and (size is None or size == info["size"])
            entry.update({"gcs_url": url, "gcs_uri": info["gs_uri"], "gcs_size": info["size"], "gcs_md5": info["md5"],
                          "gcs_verified": ok, "gcs_uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            rows.append((bid, "ok" if ok else f"uploaded but HEAD={status}", url, f"{info['size']:,} B"))
            progress.log("gcs", f"{bid}: uploaded {info['size']:,} bytes → HEAD {status}{' ✓' if ok else ' ✗'}", run_id)
        except GCSError as e:
            rows.append((bid, f"FAILED {e}", "", ""))
            progress.log("gcs", f"{bid}: FAILED {e}", run_id)
    save_deliverables(folder, deliverables)

    lines = [f"# GCS upload · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"- **Run:** `{run_id}` · **Bucket:** `gs://{args.bucket}/{cfg['prefix']}` · **URL mode:** {cfg['url_mode']}" + ("  (DRY RUN)" if args.dry_run else ""),
             "", "| Brief | Status | URL | Size |", "|---|---|---|---|"]
    lines += [f"| `{b}` | {st} | {u} | {sz} |" for b, st, u, sz in rows]
    (folder / "gcs_upload.md").write_text("\n".join(lines) + "\n")
    for b, st, u, sz in rows:
        print(f"{st:<12} {b}  {u}")
    print(f"receipt {rel(folder / 'gcs_upload.md')}   deliverables {rel(deliverables_path(folder))}")
    return 0 if all(st.startswith(("ok", "dry")) for _, st, _, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
