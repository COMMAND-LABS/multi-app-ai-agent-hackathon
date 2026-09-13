"""Step 2: outlier multiples.

    uv run python -m analysis.outliers [--channels @a @b ...] [--window since_2026-06-15]
                                       [--threshold 3.0] [--min-age-days 7] [--format long|short|both]

multiple = video views / median views of the channel's videos in the same format (long-form or
Shorts) over the window, counting only videos old enough to have matured (--min-age-days).

Reads  data/youtube/<handle>/videos/latest_<window>.csv  (+ channel/latest_profile.csv)
Writes reports/<run_id>/outliers.md and outliers.csv, and prints the summary table.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from analysis import config as pipeline_config
from analysis.run import current_run_id, rel, report_dir
from integrations.config import settings

YT_DIR = settings.data_dir / "youtube"


# ------------------------------------------------------------------ loading
def list_channels() -> list[str]:
    return sorted(p.name for p in YT_DIR.iterdir() if p.is_dir() and not p.name.startswith("_") and (p / "videos").exists())


def pick_videos_csv(handle: str, window: str | None) -> Path:
    folder = YT_DIR / handle / "videos"
    if window:
        path = folder / f"latest_{window}.csv"
        if not path.exists():
            sys.exit(f"{handle}: no pull for window '{window}' (expected {rel(path)}). Run the videos command first.")
        return path
    candidates = sorted(folder.glob("latest_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        sys.exit(f"{handle}: no videos pulled yet under {rel(folder)}")
    return candidates[0]


def load_profile(handle: str) -> dict:
    path = YT_DIR / handle / "channel" / "latest_profile.csv"
    if not path.exists():
        return {"title": handle, "subscribers": ""}
    with path.open(encoding="utf-8") as f:
        return next(csv.DictReader(f))


def load_videos(path: Path, now: datetime) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            published = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            rows.append(
                {
                    **r,
                    "views": int(r["views"] or 0),
                    "likes": int(r["likes"] or 0),
                    "comments": int(r["comments"] or 0),
                    "duration_seconds": int(r["duration_seconds"] or 0),
                    "format": "short" if r["is_short"] == "True" else "long",
                    "days_live": round((now - published).total_seconds() / 86400, 1),
                }
            )
    return rows


# ---------------------------------------------------------------- analysis
def analyze_channel(handle: str, videos: list[dict], threshold: float, min_age: float, formats: list[str]) -> dict:
    out = {"handle": handle, "groups": {}}
    for fmt in formats:
        group = [v for v in videos if v["format"] == fmt]
        mature = [v for v in group if v["days_live"] >= min_age]
        median = statistics.median(v["views"] for v in mature) if mature else 0
        for v in group:
            v["channel_median"] = median
            v["multiple"] = round(v["views"] / median, 2) if median else None
            if v["days_live"] < min_age:
                v["note"] = "too new"
                v["is_outlier"] = False
            elif v["multiple"] is not None and v["multiple"] >= threshold:
                v["note"] = "OUTLIER"
                v["is_outlier"] = True
            else:
                v["note"] = ""
                v["is_outlier"] = False
        out["groups"][fmt] = {
            "videos": sorted(group, key=lambda v: (v["multiple"] or 0), reverse=True),
            "median": median,
            "n_total": len(group),
            "n_mature": len(mature),
            "thin": 0 < len(mature) < 5,
        }
    return out


# ------------------------------------------------------------------ output
def fmt_int(n) -> str:
    return f"{int(n):,}" if n not in (None, "") else ""


def md_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(str(r.get(key, "")) for key, _ in cols) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def video_view(v: dict, with_channel: bool) -> dict:
    d = {
        "channel": v["channel"],
        "title": f"[{v['title'][:70].replace('|', '/')}]({v['url']})",
        "published": v["published_at"][:10],
        "days": f"{v['days_live']:.0f}",
        "views": fmt_int(v["views"]),
        "median": fmt_int(v["channel_median"]),
        "multiple": f"**{v['multiple']:.1f}x**" if v["is_outlier"] else (f"{v['multiple']:.1f}x" if v["multiple"] is not None else "n/a"),
        "note": v["note"],
    }
    if not with_channel:
        d.pop("channel")
    return d


def write_markdown(path: Path, run_id: str, args, results: list[dict], outliers: list[dict], now: datetime) -> None:
    lines = [
        f"# Outlier analysis · {now.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- **Run:** `{run_id}` (tool-call log: `logs/{run_id}.log`)",
        f"- **Channels:** {', '.join('@' + r['handle'] for r in results)}",
        f"- **Window:** `{args.window or 'latest pull'}`",
        f"- **Formats:** {', '.join(args.formats)} (Shorts = 60s or under)",
        f"- **Threshold:** {args.threshold:.1f}x the channel median",
        f"- **Minimum age:** {args.min_age_days:.0f} days (newer videos are listed but not judged)",
        "- **Settings from:** `pipeline.toml` [outliers] (flags override per run)",
        "",
        "**Multiple** = a video's views ÷ the median views of that channel's mature videos in the same format over the window. "
        "A multiple of 3.0x means the video did three times as well as a typical upload for that channel.",
        "",
        f"## Outliers found ({len(outliers)})",
        "",
    ]
    if outliers:
        lines.append(md_table([video_view(v, True) for v in outliers], [
            ("channel", "Channel"), ("title", "Video"), ("published", "Published"), ("views", "Views"),
            ("median", "Channel median"), ("multiple", "Multiple"),
        ]))
    else:
        lines.append("_No video crossed the threshold._")
    lines += ["", "## Per-channel detail", ""]
    for r in results:
        prof = r["profile"]
        lines.append(f"### @{r['handle']} — {prof.get('title', '')} ({fmt_int(prof.get('subscribers'))} subscribers)")
        lines.append("")
        for fmt, g in r["groups"].items():
            label = "Long-form" if fmt == "long" else "Shorts"
            n_out = sum(1 for v in g["videos"] if v["is_outlier"])
            warn = " ⚠️ thin baseline (fewer than 5 mature videos)" if g["thin"] else ""
            if g["n_total"] == 0:
                lines.append(f"**{label}:** none in window.")
                lines.append("")
                continue
            lines.append(
                f"**{label}:** {g['n_total']} videos, {g['n_mature']} mature · median {fmt_int(g['median'])} views · "
                f"{n_out} outlier{'s' if n_out != 1 else ''}{warn}"
            )
            lines.append("")
            lines.append(md_table([video_view(v, False) for v in g["videos"]], [
                ("title", "Video"), ("published", "Published"), ("days", "Days live"), ("views", "Views"),
                ("multiple", "Multiple"), ("note", "Note"),
            ]))
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


CSV_COLS = [
    "run_id", "channel", "channel_id", "channel_title", "video_id", "title", "url", "published_at", "days_live", "format",
    "duration_seconds", "views", "likes", "comments", "channel_median", "multiple", "is_outlier", "note", "description",
]


def write_csv(path: Path, run_id: str, results: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in results:
            for g in r["groups"].values():
                for v in g["videos"]:
                    w.writerow({**{k: v.get(k, "") for k in CSV_COLS}, "run_id": run_id, "channel_title": r["profile"].get("title", "")})


def print_summary(results: list[dict], outliers: list[dict]) -> None:
    print(f"\n{'channel':<18} {'fmt':<5} {'videos':>6} {'mature':>6} {'median':>9} {'outliers':>8}")
    for r in results:
        for fmt, g in r["groups"].items():
            n_out = sum(1 for v in g["videos"] if v["is_outlier"])
            print(f"{r['handle']:<18} {fmt:<5} {g['n_total']:>6} {g['n_mature']:>6} {fmt_int(g['median']):>9} {n_out:>8}{'  (thin)' if g['thin'] else ''}")
    print(f"\nOutliers ({len(outliers)}):")
    for v in outliers:
        print(f"  {v['multiple']:>5.1f}x  {v['channel']:<18} {fmt_int(v['views']):>9}  {v['title'][:70]}")


# -------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    cfg = pipeline_config.section("outliers")
    chans = pipeline_config.section("channels")["handles"]
    p = argparse.ArgumentParser(prog="python -m analysis.outliers", description=__doc__ + "\nDefaults come from pipeline.toml [outliers].", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channels", nargs="*", default=chans or None, help="handles; default: pipeline.toml [channels], else every channel under data/youtube/")
    p.add_argument("--window", help="which pull to use, e.g. since_2026-06-15 (default: most recent pull per channel)")
    p.add_argument("--threshold", type=float, default=cfg["threshold"], help="multiple at/above which a video is an outlier (default %(default)s)")
    p.add_argument("--min-age-days", type=float, default=cfg["min_age_days"], help="videos younger than this are listed but not judged (default %(default)s)")
    p.add_argument("--format", dest="formats", choices=["long", "short", "both"], default=cfg["format"], help="(default %(default)s)")
    p.add_argument("--run-id", help="override the run id (default: current tool-call log stem)")
    args = p.parse_args(argv)
    args.formats = ["long", "short"] if args.formats == "both" else [args.formats]

    now = datetime.now(timezone.utc)
    run_id = args.run_id or current_run_id()
    handles = [h.lstrip("@").lower() for h in (args.channels or list_channels())]
    if not handles:
        sys.exit("No channels found. Pull data first with: uv run python -m integrations.youtube videos @handle --days 90")

    results = []
    for h in handles:
        videos = load_videos(pick_videos_csv(h, args.window), now)
        for v in videos:
            v["channel"] = h
        r = analyze_channel(h, videos, args.threshold, args.min_age_days, args.formats)
        r["profile"] = load_profile(h)
        results.append(r)
    outliers = sorted(
        (v for r in results for g in r["groups"].values() for v in g["videos"] if v["is_outlier"]),
        key=lambda v: v["multiple"], reverse=True,
    )

    out = report_dir(run_id)
    write_markdown(out / "outliers.md", run_id, args, results, outliers, now)
    write_csv(out / "outliers.csv", run_id, results)
    print_summary(results, outliers)
    print(f"\nreport  {rel(out / 'outliers.md')}\ncsv     {rel(out / 'outliers.csv')}\nrun_id  {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
