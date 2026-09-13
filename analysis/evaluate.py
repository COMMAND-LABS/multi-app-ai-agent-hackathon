"""Step 8: evaluate a run end to end and write a PASS/FAIL report.

    uv run python -m analysis.evaluate [--run-id X]

Checks every artifact the pipeline should have produced for the run and whether they agree with
each other: data → outliers → repeatability → Airtable → brief → video → GCS → Metricool → progress
log. Writes reports/<run_id>/evaluation.md and exits 1 if any check FAILS (WARN never fails).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from analysis import config as pipeline_config
from analysis import progress
from analysis.run import current_run_id, rel, report_dir
from integrations.config import PROJECT_ROOT

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


def ffprobe(path: Path) -> dict:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60).stdout
        d = json.loads(out or "{}")
        v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
        return {"duration": float(d.get("format", {}).get("duration", 0) or 0), "width": v.get("width"), "height": v.get("height"),
                "audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate(run_id: str) -> tuple[list[tuple[str, str, str]], dict]:
    folder = report_dir(run_id)
    vcfg, ecfg, rcfg = pipeline_config.section("video"), pipeline_config.section("evaluate"), pipeline_config.section("repeatability")
    checks: list[tuple[str, str, str]] = []
    stats: dict = {}

    def add(name, status, detail=""):
        checks.append((name, status, detail))

    # --- step 2: outliers
    oc = folder / "outliers.csv"
    if not oc.exists():
        add("outliers.csv exists", FAIL, rel(oc)); outliers = []
    else:
        outliers = read_csv(oc)
        flagged = [r for r in outliers if r["is_outlier"] == "True"]
        stats["videos"], stats["outliers"] = len(outliers), len(flagged)
        add("outliers.csv exists", PASS, f"{len(outliers)} videos, {len(flagged)} flagged")
        bad = [r for r in flagged if float(r["multiple"] or 0) < float(pipeline_config.section("outliers")["threshold"])]
        add("every flagged outlier meets the threshold", FAIL if bad else PASS, f"{len(bad)} below threshold" if bad else "")
        add("outliers.md written", PASS if (folder / "outliers.md").exists() else FAIL)

    # --- step 3: repeatability
    rc = folder / "repeatability.csv"
    if not rc.exists():
        add("repeatability.csv exists", FAIL); ideas = []
    else:
        ideas = read_csv(rc)
        rep = [r for r in ideas if r["repeatable"] == "True"]
        stats["checked"], stats["repeatable"] = len(ideas), len(rep)
        add("repeatability.csv exists", PASS, f"{len(ideas)} checked, {len(rep)} repeatable")
        flagged_ids = {r["video_id"] for r in outliers if r["is_outlier"] == "True"}
        orphan = [r for r in ideas if r["source_video_id"] not in flagged_ids]
        add("every checked idea is a flagged outlier", FAIL if orphan else PASS, f"{len(orphan)} orphans" if orphan else "")
        wrong = [r for r in rep if int(r["repeatability_score"]) < rcfg["min_channels"]]
        add("every repeatable idea meets min_channels", FAIL if wrong else PASS, f"{len(wrong)} below {rcfg['min_channels']}" if wrong else "")
        mc = folder / "repeatability_matches.csv"
        if mc.exists():
            matches = read_csv(mc)
            own = {r["source_video_id"]: r["source_channel_title"].lower() for r in ideas}
            leak = [m for m in matches if m["match_channel"].lower() == own.get(m["idea_video_id"], "").lower()]
            add("evidence excludes each idea's own channel", FAIL if leak else PASS, f"{len(leak)} self-matches" if leak else f"{len(matches)} matches")
        else:
            add("repeatability_matches.csv exists", WARN, "no evidence file")

    # --- step 4: airtable
    sync = folder / "airtable_sync.md"
    if sync.exists():
        txt = sync.read_text()
        live = "**Mode:** live" in txt
        m = re.search(r"\*\*Records:\*\* (\d+) sent · (\d+) created · (\d+) updated", txt)
        sent = int(m.group(1)) if m else -1
        add("airtable sync ran live", PASS if live else WARN, "dry run only" if not live else f"{sent} sent")
        if live and ideas:
            add("airtable rows == repeatable ideas", PASS if sent == stats.get("repeatable") else WARN, f"{sent} vs {stats.get('repeatable')}")
    else:
        add("airtable_sync.md exists", WARN, "step 4 not run")

    # --- steps 5-7: briefs, videos, gcs, metricool
    agent_dir = (PROJECT_ROOT / vcfg["agent_dir"]).resolve()
    briefs = sorted((agent_dir / "briefs").glob(f"{run_id}__*.md")) if (agent_dir / "briefs").exists() else []
    add("brief(s) handed to video agent", PASS if briefs else WARN, f"{len(briefs)} brief(s)" if briefs else "step 5 not run")
    dpath = folder / "deliverables.json"
    deliverables = json.loads(dpath.read_text()) if dpath.exists() else {"briefs": {}}
    for b in briefs:
        bid = b.stem
        text = b.read_text()
        spec = {k.strip(): v.strip() for k, v in re.findall(r"^- (workflow|length|aspect|voice|music):\s*(.+)$", text, re.M)}
        want_secs = float(re.sub(r"[^\d.]", "", spec.get("length", vcfg["length"])) or 0)
        w, h = (int(x) for x in spec.get("aspect", vcfg["aspect"]).split("x"))
        voice_requested = spec.get("voice", "none") != "none"
        add(f"{bid}: brief has no links/emails", FAIL if re.search(r"https?://|[\w.+-]+@[\w-]+\.\w+", text) else PASS)
        add(f"{bid}: brief carries run_id", PASS if run_id in text else FAIL)
        video = agent_dir / "output" / bid / "video.mp4"
        if not video.exists():
            add(f"{bid}: video rendered", WARN, "not (yet) delivered"); continue
        info = ffprobe(video)
        add(f"{bid}: video rendered", PASS, f"{info.get('duration', 0):.1f}s {info.get('width')}x{info.get('height')}")
        if want_secs:
            off = abs(info.get("duration", 0) - want_secs) / want_secs
            add(f"{bid}: duration within ±{ecfg['duration_tolerance']:.0%} of {spec.get('length', vcfg['length'])}", PASS if off <= ecfg["duration_tolerance"] else WARN, f"{off:.0%} off")
        add(f"{bid}: aspect is {w}x{h}", PASS if (info.get("width"), info.get("height")) == (w, h) else FAIL)
        if voice_requested and ecfg["require_audio"]:
            add(f"{bid}: audio track present (voice requested)", PASS if info.get("audio") else FAIL)
        elif not voice_requested:
            add(f"{bid}: silent by design ({spec.get('workflow', '?')})", PASS if not info.get("audio") else WARN, "has audio" if info.get("audio") else "")
        summ = agent_dir / "output" / bid / "SUMMARY.md"
        add(f"{bid}: SUMMARY.md carries run_id", PASS if summ.exists() and run_id in summ.read_text() else FAIL)
        e = deliverables["briefs"].get(bid, {})
        if e.get("gcs_url") and not e.get("gcs_uploaded_at"):
            add(f"{bid}: uploaded to GCS", WARN, "dry run only (URL computed, nothing uploaded)")
        elif e.get("gcs_url"):
            try:
                r = requests.head(e["gcs_url"], timeout=20, allow_redirects=True)
                ok = r.status_code == 200
                add(f"{bid}: GCS URL reachable", PASS if ok else FAIL, f"HEAD {r.status_code}")
                cl = r.headers.get("Content-Length")
                if ok and cl and e.get("gcs_size"):
                    add(f"{bid}: GCS size matches upload", PASS if int(cl) == e["gcs_size"] else FAIL, f"{cl} vs {e['gcs_size']}")
            except requests.RequestException as ex:
                add(f"{bid}: GCS URL reachable", FAIL, str(ex)[:80])
        else:
            add(f"{bid}: uploaded to GCS", WARN, "step 6 not run")
        if e.get("metricool_post_id"):
            add(f"{bid}: on Metricool calendar", PASS, f"post {e['metricool_post_id']} ({'draft' if e.get('metricool_draft') else 'scheduled'}) at {e.get('metricool_when')}")
        elif e.get("metricool_payload"):
            add(f"{bid}: on Metricool calendar", WARN, "payload built (dry run), not sent")
        else:
            add(f"{bid}: on Metricool calendar", WARN, "step 7 not run")

    # --- progress log coverage
    plines = progress.lines(run_id)
    steps_seen = {m.group(1) for l in plines if (m := re.match(r"\S+ \S+\s+\S+\s+\S+\s+(\S+)", l))}
    add("progress.log has entries for this run", PASS if plines else FAIL, f"{len(plines)} lines · steps: {', '.join(sorted(steps_seen))}")
    stats["progress_lines"] = len(plines)
    return checks, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m analysis.evaluate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id")
    args = p.parse_args(argv)
    run_id = args.run_id or current_run_id()
    folder = report_dir(run_id)
    checks, stats = evaluate(run_id)
    n = {s: sum(1 for _, st, _ in checks if st == s) for s in (PASS, WARN, FAIL, SKIP)}
    verdict = "FAIL" if n[FAIL] else ("PASS with warnings" if n[WARN] else "PASS")
    icon = {PASS: "✅", WARN: "⚠️", FAIL: "❌", SKIP: "⏭"}
    lines = [f"# Evaluation · run `{run_id}` · **{verdict}**", "",
             f"- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {n[PASS]} pass · {n[WARN]} warn · {n[FAIL]} fail",
             f"- Funnel: {stats.get('videos', '?')} videos → {stats.get('outliers', '?')} outliers → {stats.get('checked', '?')} checked → {stats.get('repeatable', '?')} repeatable",
             "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {name} | {icon[st]} {st} | {detail} |" for name, st, detail in checks]
    (folder / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, st, detail in checks:
        print(f"{icon[st]} {st:<4} {name:<55} {detail}")
    print(f"\n{verdict}: {n[PASS]} pass, {n[WARN]} warn, {n[FAIL]} fail → {rel(folder / 'evaluation.md')}")
    progress.log("evaluate", f"{verdict}: {n[PASS]} pass, {n[WARN]} warn, {n[FAIL]} fail → {rel(folder / 'evaluation.md')}", run_id)
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
