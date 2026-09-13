"""Step 7: put the video on the Metricool content calendar.

    uv run python -m integrations.metricool.schedule [--run-id X] [--brief-id ID] [--networks instagram tiktok]
                                                     [--when "2026-09-15T10:00:00"] [--draft/--no-draft] [--dry-run]

Reads reports/<run_id>/deliverables.json (the GCS URL from step 6) and repeatability.csv (the idea
title), builds the post, creates it (draft by default so a human approves it in Metricool), and
records the post id in deliverables.json + metricool_schedule.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from analysis import config as pipeline_config
from analysis import progress
from analysis.run import current_run_id, rel, report_dir
from integrations.gcs.upload import load_deliverables, save_deliverables
from integrations.metricool import MetricoolAPIError, MetricoolClient
from integrations.metricool.client import build_post


def idea_titles(folder: Path) -> dict[str, dict]:
    path = folder / "repeatability.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["source_video_id"]: r for r in csv.DictReader(f)}


def caption(template: str, idea: dict, run_id: str) -> str:
    return template.format(title=idea.get("idea_title", ""), score=idea.get("repeatability_score", ""),
                           channel=idea.get("source_channel", ""), run_id=run_id).strip()


def main(argv: list[str] | None = None) -> int:
    cfg = pipeline_config.section("metricool")
    p = argparse.ArgumentParser(prog="python -m integrations.metricool.schedule", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id")
    p.add_argument("--brief-id", help="default: every brief in deliverables.json that has a gcs_url")
    p.add_argument("--networks", nargs="*", default=cfg["networks"])
    p.add_argument("--when", help="local datetime YYYY-MM-DDTHH:MM:SS in the brand timezone (default: [metricool] days_ahead + time)")
    p.add_argument("--draft", dest="draft", action="store_true", default=cfg["draft"])
    p.add_argument("--no-draft", dest="draft", action="store_false")
    p.add_argument("--dry-run", action="store_true", help="build and record the payload, do not call Metricool")
    args = p.parse_args(argv)
    run_id = args.run_id or current_run_id()
    folder = report_dir(run_id)
    tz = cfg["timezone"]

    deliverables = load_deliverables(folder)
    briefs = {b: e for b, e in deliverables["briefs"].items() if e.get("gcs_url")}
    if args.brief_id:
        briefs = {args.brief_id: briefs.get(args.brief_id) or {}}
        if not briefs[args.brief_id].get("gcs_url"):
            sys.exit(f"{args.brief_id} has no gcs_url in {rel(folder / 'deliverables.json')}; run integrations.gcs.upload first.")
    if not briefs:
        sys.exit(f"Nothing to schedule: no gcs_url in {rel(folder / 'deliverables.json')}. Run integrations.gcs.upload first.")

    if args.when:
        when_local = args.when
    else:
        now_local = datetime.now(ZoneInfo(tz))
        hh, mm = (int(x) for x in cfg["time"].split(":"))
        when_local = (now_local + timedelta(days=cfg["days_ahead"])).replace(hour=hh, minute=mm, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")

    titles = idea_titles(folder)
    client = None
    if not args.dry_run:
        try:
            client = MetricoolClient()
        except MetricoolAPIError as e:
            progress.log("metricool", f"FAILED: {e}", run_id); print(f"error: {e}", file=sys.stderr); return 1

    rows = []
    for bid, entry in briefs.items():
        vid = bid.split("__", 1)[1] if "__" in bid else bid
        idea = titles.get(vid, {"idea_title": bid})
        text = caption(cfg["caption_template"], idea, run_id)
        info = build_post(text, entry["gcs_url"], args.networks, when_local, tz, draft=args.draft, auto_publish=cfg["auto_publish"],
                          title=idea.get("idea_title", ""), declare_ai=cfg["declare_ai"], instagram_type=cfg["instagram_type"],
                          youtube_privacy=cfg["youtube_privacy"], tiktok_privacy=cfg["tiktok_privacy"], tags=cfg["tags"])
        entry["metricool_payload"] = info
        if args.dry_run:
            rows.append((bid, "dry-run", "-", when_local)); continue
        try:
            res = client.create_post(info)
            post_id = (res.get("data") or res).get("id") if isinstance(res, dict) else None
            entry.update({"metricool_post_id": post_id, "metricool_networks": args.networks, "metricool_when": f"{when_local} {tz}",
                          "metricool_draft": args.draft, "metricool_scheduled_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            rows.append((bid, "ok", str(post_id), when_local))
            progress.log("metricool", f"{bid}: {'draft' if args.draft else 'scheduled'} post {post_id} for {when_local} {tz} on {','.join(args.networks)}", run_id)
        except MetricoolAPIError as e:
            rows.append((bid, f"FAILED {e}", "-", when_local))
            progress.log("metricool", f"{bid}: FAILED {e}", run_id)
    save_deliverables(folder, deliverables)

    lines = [f"# Metricool schedule · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"- **Run:** `{run_id}` · **Networks:** {', '.join(args.networks)} · **When:** {when_local} {tz} · **Draft:** {args.draft} · **Auto-publish:** {cfg['auto_publish']}" + ("  (DRY RUN)" if args.dry_run else ""),
             "", "| Brief | Status | Post id | Publish at |", "|---|---|---|---|"]
    lines += [f"| `{b}` | {st} | `{pid}` | {w} |" for b, st, pid, w in rows]
    lines += ["", "## Payload sent (first brief)", "", "```json", json.dumps(next(iter(briefs.values()))["metricool_payload"], indent=2), "```"]
    (folder / "metricool_schedule.md").write_text("\n".join(lines) + "\n")
    for b, st, pid, w in rows:
        print(f"{st:<10} {b}  post={pid}  at {w} {tz}")
    print(f"receipt {rel(folder / 'metricool_schedule.md')}")
    return 0 if all(st.startswith(("ok", "dry")) for _, st, _, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
