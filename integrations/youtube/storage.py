"""Write pulled YouTube data into DATA_DIR/youtube/<channel>/<kind>/ as JSON (+ CSV for tabular data).

Data that is not tied to one channel (search results, ad-hoc video lookups) goes under `_global/`.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from integrations.config import settings


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text.lstrip("@")).strip("-")[:80] or "data"


def channel_slug(handle_or_id: str) -> str:
    """Folder name for a channel: handle without '@', lowercased; falls back to the ID."""
    return _slug(handle_or_id).lower()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save(
    kind: str,
    name: str,
    payload: Any,
    rows: list[dict] | None = None,
    *,
    channel: str | None = None,
    meta: dict | None = None,
) -> dict[str, Path]:
    """Save raw payload as timestamped JSON plus a `latest` copy; optional CSV of flattened rows.

    Files land in data/youtube/<channel>/<kind>/ (or data/youtube/_global/<kind>/ if no channel).
    Returns the paths written, keyed by "json", "latest", and (if rows) "csv", "latest_csv".
    """
    folder = settings.data_dir / "youtube" / (channel_slug(channel) if channel else "_global") / kind
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{_now_stamp()}_{_slug(name)}"
    envelope = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "name": name,
        "channel": channel,
        "count": len(payload) if isinstance(payload, list) else 1,
        **(meta or {}),
        "data": payload,
    }
    json_path = folder / f"{stem}.json"
    json_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False))
    latest = folder / f"latest_{_slug(name)}.json"
    latest.write_text(json_path.read_text())
    written = {"json": json_path, "latest": latest}

    if rows:
        csv_path = folder / f"{stem}.csv"
        fieldnames = list({k: None for r in rows for k in r})
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        latest_csv = folder / f"latest_{_slug(name)}.csv"
        latest_csv.write_text(csv_path.read_text())
        written["csv"] = csv_path
        written["latest_csv"] = latest_csv
    return written


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(settings.data_dir.parent))
    except ValueError:
        return str(path)
