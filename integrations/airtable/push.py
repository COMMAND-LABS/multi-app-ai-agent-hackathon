"""Step 4: push repeatable ideas from a run into Airtable.

    uv run python -m integrations.airtable.push [--run-id X] [--table "Repeatable Ideas"] [--all] [--dry-run]

Reads  reports/<run_id>/repeatability.csv (+ repeatability_matches.csv for evidence)
Writes rows to the Airtable table (created on first use), keyed on Run ID + Source Video ID so
       re-running the same run updates instead of duplicating.
Writes reports/<run_id>/airtable_sync.md describing exactly what was sent, with record IDs.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analysis import config as pipeline_config
from analysis.run import current_run_id, rel, report_dir
from integrations.airtable import AirtableAPIError, AirtableClient
from integrations.config import settings

DEFAULT_TABLE = "Repeatable Ideas"
MERGE_ON = ["Run ID", "Source Video ID"]

TABLE_FIELDS = [
    {"name": "Idea", "type": "singleLineText"},
    {"name": "Run ID", "type": "singleLineText"},
    {"name": "Found At", "type": "dateTime", "options": {"dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "utc"}},
    {"name": "Status", "type": "singleSelect", "options": {"choices": [{"name": "New"}, {"name": "In progress"}, {"name": "Used"}, {"name": "Rejected"}]}},
    {"name": "Repeatable", "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}},
    {"name": "Source Channel", "type": "singleLineText"},
    {"name": "Source Video ID", "type": "singleLineText"},
    {"name": "Source URL", "type": "url"},
    {"name": "Source Views", "type": "number", "options": {"precision": 0}},
    {"name": "Outlier Multiple", "type": "number", "options": {"precision": 1}},
    {"name": "Topic Query", "type": "singleLineText"},
    {"name": "Repeatability Score", "type": "number", "options": {"precision": 0}},
    {"name": "Similar Videos", "type": "number", "options": {"precision": 0}},
    {"name": "Strong Hits", "type": "number", "options": {"precision": 0}},
    {"name": "Median Match Views", "type": "number", "options": {"precision": 0}},
    {"name": "Evidence", "type": "multilineText"},
    {"name": "Description", "type": "multilineText"},
    {"name": "Report", "type": "singleLineText"},
]


def load_ideas(folder: Path, include_all: bool) -> list[dict]:
    path = folder / "repeatability.csv"
    if not path.exists():
        sys.exit(f"{rel(path)} not found. Run `uv run python -m analysis.repeatability` first.")
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows if include_all else [r for r in rows if r["repeatable"] == "True"]


def load_evidence(folder: Path) -> dict[str, list[dict]]:
    path = folder / "repeatability_matches.csv"
    by_idea: dict[str, list[dict]] = defaultdict(list)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for m in csv.DictReader(f):
                by_idea[m["idea_video_id"]].append(m)
    for ms in by_idea.values():
        ms.sort(key=lambda m: (m["strong_hit"] != "True", -int(m["match_views"])))
    return by_idea


def to_record(idea: dict, matches: list[dict], run_id: str) -> dict:
    evidence = "\n".join(
        f"{'✔' if m['strong_hit'] == 'True' else '·'} {m['match_channel']} — {int(m['match_views']):,} views — {m['match_title']} — {m['url']}"
        for m in matches[:8]
    ) or "No similar videos found on other channels."
    return {
        "Idea": idea["idea_title"],
        "Run ID": run_id,
        "Found At": idea["found_at"],
        "Status": "New",
        "Repeatable": idea["repeatable"] == "True",
        "Source Channel": "@" + idea["source_channel"],
        "Source Video ID": idea["source_video_id"],
        "Source URL": idea["source_url"],
        "Source Views": int(idea["source_views"]),
        "Outlier Multiple": float(idea["outlier_multiple"]),
        "Topic Query": idea["topic_query"],
        "Repeatability Score": int(idea["repeatability_score"]),
        "Similar Videos": int(idea["similar_videos"]),
        "Strong Hits": int(idea["strong_hits"]),
        "Median Match Views": int(idea["median_match_views"]),
        "Evidence": evidence,
        "Description": (idea["description"] or "")[:20000],
        "Report": f"reports/{run_id}/repeatability.md",
    }


def write_sync_report(folder: Path, run_id: str, table: str, base_id: str, records: list[dict], result: dict | None, created_table: bool, dry: bool) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ids_by_key = {}
    if result:
        for rec in result["records"]:
            f = rec.get("fields", {})
            ids_by_key[(f.get("Run ID"), f.get("Source Video ID"))] = rec["id"]
    L = [
        f"# Airtable sync · {now}",
        "",
        f"- **Run:** `{run_id}` (log: `logs/{run_id}.log`, source: `reports/{run_id}/repeatability.md`)",
        f"- **Base:** `{base_id}` · **Table:** `{table}`" + ("  (created in this run)" if created_table else ""),
        f"- **Mode:** {'DRY RUN — nothing sent' if dry else 'live'}",
        f"- **Records:** {len(records)} sent · {len(result['created']) if result else 0} created · {len(result['updated']) if result else 0} updated",
        f"- **Matched on:** {' + '.join(MERGE_ON)} (re-running the same run updates rows instead of duplicating)",
        "",
        "| Idea | Source | Multiple | Score | Airtable record |",
        "|---|---|---|---|---|",
    ]
    for r in records:
        rid = ids_by_key.get((r["Run ID"], r["Source Video ID"]), "(dry run)" if dry else "?")
        L.append(f"| {r['Idea'][:60].replace('|', '/')} | {r['Source Channel']} | {r['Outlier Multiple']:.1f}x | {r['Repeatability Score']} | `{rid}` |")
    path = folder / "airtable_sync.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    cfg = pipeline_config.section("airtable")
    p = argparse.ArgumentParser(prog="python -m integrations.airtable.push", description=__doc__ + "\nDefaults come from pipeline.toml [airtable].", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", help="run to push (default: current log stem)")
    p.add_argument("--table", default=cfg["table"] or DEFAULT_TABLE, help="(default %(default)s)")
    p.add_argument("--all", action="store_true", default=cfg["push_all"], help="push every checked idea, not only the repeatable ones")
    p.add_argument("--dry-run", action="store_true", help="build the records and the sync report without calling Airtable")
    args = p.parse_args(argv)
    run_id = args.run_id or current_run_id()
    folder = report_dir(run_id)

    ideas = load_ideas(folder, args.all)
    evidence = load_evidence(folder)
    records = [to_record(i, evidence.get(i["source_video_id"], []), run_id) for i in ideas]
    if not records:
        print("No repeatable ideas in this run; nothing to push.")
        return 0

    print(f"{len(records)} idea(s) to push to table '{args.table}' for run {run_id}")
    for r in records:
        print(f"  {r['Outlier Multiple']:>5.1f}x  score={r['Repeatability Score']:<3} {r['Source Channel']:<18} {r['Idea'][:60]}")

    result, created_table = None, False
    if args.dry_run:
        base_id = settings.airtable.base_id or "(not set)"
    else:
        try:
            client = AirtableClient()
            _, created_table = client.ensure_table(args.table, TABLE_FIELDS, "Repeatable YouTube ideas found by the outlier → repeatability pipeline. One row per idea per run.")
            result = client.upsert(args.table, records, MERGE_ON)
        except AirtableAPIError as e:
            print(f"error: {e}", file=sys.stderr)
            if e.status == 403 and "schema" in str(e).lower() or e.status == 403:
                print("hint: the token may lack schema.bases:write. Create the table manually with the fields in integrations/airtable/push.py, or add the scope.", file=sys.stderr)
            return 1
        base_id = client.base_id
        print(f"\nAirtable: {len(result['created'])} created, {len(result['updated'])} updated" + ("  (table created)" if created_table else ""))

    path = write_sync_report(folder, run_id, args.table, base_id, records, result, created_table, args.dry_run)
    print(f"sync report  {rel(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
