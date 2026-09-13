"""Step 3: repeatability of each outlier idea.

    uv run python -m analysis.repeatability [--run-id X] [--days-back 180] [--per-query 25]
                                            [--min-similarity 0.4] [--min-views 10000] [--min-channels 3]

For every outlier in reports/<run_id>/outliers.csv:
  1. build a topic query from the title,
  2. search YouTube for videos on that topic (100 quota units per query),
  3. fetch their stats and channel sizes (1-2 units),
  4. keep candidates whose title+description overlap the outlier's (similarity >= --min-similarity),
     excluding the source channel,
  5. count how many *distinct other channels* have a strong hit (views >= --min-views).

An idea is REPEATABLE when at least --min-channels other channels succeeded with it.

Writes reports/<run_id>/repeatability.md, repeatability.csv (one row per idea) and
repeatability_matches.csv (one row per similar video = the evidence).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis import config as pipeline_config
from analysis.run import current_run_id, rel, report_dir
from analysis.text import similarity, topic_query
from integrations.youtube import YouTubeAPIError, YouTubeClient
from integrations.youtube.client import flatten_video
from integrations.youtube.storage import save


def load_outliers(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["is_outlier"] == "True"]
    for r in rows:
        r["views"] = int(r["views"]); r["multiple"] = float(r["multiple"])
    return sorted(rows, key=lambda r: r["multiple"], reverse=True)


def fmt_int(n) -> str:
    return f"{int(n):,}" if n not in (None, "") else ""


# ---------------------------------------------------------------- per idea
def scan_idea(client: YouTubeClient, idea: dict, args, published_after: str) -> dict:
    query = topic_query(idea["title"])
    results = client.search(query, kind="video", limit=args.per_query, order="relevance", published_after=published_after)
    raw_paths = save("search", f"{idea['video_id']}_{query}", results, channel=None,
                     meta={"run_id": args.run_id, "source_video_id": idea["video_id"], "query": query})
    ids = [r["id"]["videoId"] for r in results if r["id"].get("videoId") and r["id"]["videoId"] != idea["video_id"]]
    videos = client.videos(ids) if ids else []
    chan_ids = sorted({v["snippet"]["channelId"] for v in videos})
    subs: dict[str, int] = {}
    for i in range(0, len(chan_ids), 50):
        data = client._get(f"https://www.googleapis.com/youtube/v3/channels",
                           {"part": "statistics,snippet", "id": ",".join(chan_ids[i:i + 50])})
        for c in data.get("items", []):
            subs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)

    matches = []
    for v in videos:
        flat = flatten_video(v)
        if flat["channel_id"] == idea.get("channel_id") or flat["channel_title"].lower() == idea["channel_title"].lower():
            continue
        sim = similarity(idea["title"], idea["description"], flat["title"], flat["description"])
        if sim < args.min_similarity:
            continue
        sub_count = subs.get(flat["channel_id"], 0)
        matches.append({
            "run_id": args.run_id,
            "idea_video_id": idea["video_id"],
            "idea_title": idea["title"],
            "match_video_id": flat["video_id"],
            "match_title": flat["title"],
            "match_channel": flat["channel_title"],
            "match_channel_id": flat["channel_id"],
            "match_subscribers": sub_count,
            "match_views": flat["views"],
            "views_per_sub": round(flat["views"] / sub_count, 2) if sub_count else "",
            "match_published": flat["published_at"][:10],
            "similarity": sim,
            "strong_hit": flat["views"] >= args.min_views,
            "url": flat["url"],
        })
    matches.sort(key=lambda m: m["match_views"], reverse=True)
    strong_channels = {m["match_channel_id"] for m in matches if m["strong_hit"]}
    score = len(strong_channels)
    return {
        "run_id": args.run_id,
        "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "idea_title": idea["title"],
        "topic_query": query,
        "source_channel": idea["channel"],
        "source_channel_title": idea["channel_title"],
        "source_video_id": idea["video_id"],
        "source_url": idea["url"],
        "source_views": idea["views"],
        "outlier_multiple": idea["multiple"],
        "searched": len(results),
        "similar_videos": len(matches),
        "distinct_channels": len({m["match_channel_id"] for m in matches}),
        "strong_hits": sum(1 for m in matches if m["strong_hit"]),
        "repeatability_score": score,
        "median_match_views": int(statistics.median(m["match_views"] for m in matches)) if matches else 0,
        "repeatable": score >= args.min_channels,
        "description": idea["description"],
        "raw_search_file": rel(raw_paths["json"]),
        "matches": matches,
    }


# ------------------------------------------------------------------ output
def write_markdown(path: Path, args, ideas: list[dict], published_after: str, quota_units: int) -> None:
    rep = [i for i in ideas if i["repeatable"]]
    L = [
        f"# Repeatability analysis · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- **Run:** `{args.run_id}` (log: `logs/{args.run_id}.log`, outliers: `reports/{args.run_id}/outliers.md`)",
        f"- **Ideas checked:** {len(ideas)} outliers",
        f"- **Search scope:** YouTube videos published since {published_after[:10]} (last {args.days_back} days), top {args.per_query} results per query",
        f"- **Similar** = at least {args.min_similarity:.0%} of the outlier's title keywords appear in the candidate's title + description",
        f"- **Strong hit** = a similar video from another channel with at least {fmt_int(args.min_views)} views",
        f"- **Repeatable** = strong hits on at least {args.min_channels} distinct other channels",
        f"- **Quota spent:** about {fmt_int(quota_units)} units",
        "- **Settings from:** `pipeline.toml` [repeatability] (flags override per run)",
        "",
        f"## Repeatable ideas ({len(rep)} of {len(ideas)})",
        "",
    ]
    if rep:
        L.append("| Idea | Source | Multiple | Other channels w/ strong hit | Similar videos | Median match views |")
        L.append("|---|---|---|---|---|---|")
        for i in rep:
            L.append(f"| [{i['idea_title'][:60].replace('|', '/')}]({i['source_url']}) | @{i['source_channel']} | {i['outlier_multiple']:.1f}x | **{i['repeatability_score']}** | {i['similar_videos']} | {fmt_int(i['median_match_views'])} |")
    else:
        L.append("_None met the bar._")
    L += ["", "## Every idea, with evidence", ""]
    for i in ideas:
        verdict = "✅ REPEATABLE" if i["repeatable"] else "❌ not repeatable"
        L.append(f"### {verdict} · {i['idea_title']}")
        L.append("")
        L.append(f"- Source: @{i['source_channel']} · {fmt_int(i['source_views'])} views · {i['outlier_multiple']:.1f}x · [{i['source_video_id']}]({i['source_url']})")
        L.append(f"- Query: `{i['topic_query']}` → {i['searched']} results → {i['similar_videos']} similar on {i['distinct_channels']} other channels → {i['strong_hits']} strong hits on **{i['repeatability_score']}** channels")
        L.append(f"- Raw search saved to `{i['raw_search_file']}`")
        L.append("")
        if i["matches"]:
            L.append("| Match | Channel | Subs | Views | Views/sub | Published | Similarity | Strong |")
            L.append("|---|---|---|---|---|---|---|---|")
            for m in i["matches"][:12]:
                L.append(f"| [{m['match_title'][:55].replace('|', '/')}]({m['url']}) | {m['match_channel'][:25]} | {fmt_int(m['match_subscribers'])} | {fmt_int(m['match_views'])} | {m['views_per_sub']} | {m['match_published']} | {m['similarity']:.2f} | {'✔' if m['strong_hit'] else ''} |")
            if len(i["matches"]) > 12:
                L.append(f"\n_{len(i['matches']) - 12} more in repeatability_matches.csv_")
        else:
            L.append("_No similar videos found on other channels._")
        L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


IDEA_COLS = ["run_id", "found_at", "idea_title", "topic_query", "source_channel", "source_channel_title", "source_video_id",
             "source_url", "source_views", "outlier_multiple", "searched", "similar_videos", "distinct_channels", "strong_hits",
             "repeatability_score", "median_match_views", "repeatable", "raw_search_file", "description"]
MATCH_COLS = ["run_id", "idea_video_id", "idea_title", "match_video_id", "match_title", "match_channel", "match_channel_id",
              "match_subscribers", "match_views", "views_per_sub", "match_published", "similarity", "strong_hit", "url"]


def write_csvs(folder: Path, ideas: list[dict]) -> None:
    with (folder / "repeatability.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=IDEA_COLS); w.writeheader()
        for i in ideas:
            w.writerow({k: i[k] for k in IDEA_COLS})
    with (folder / "repeatability_matches.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MATCH_COLS); w.writeheader()
        for i in ideas:
            for m in i["matches"]:
                w.writerow({k: m[k] for k in MATCH_COLS})


# -------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    cfg = pipeline_config.section("repeatability")
    p = argparse.ArgumentParser(prog="python -m analysis.repeatability", description=__doc__ + "\nDefaults come from pipeline.toml [repeatability].", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", help="run whose outliers.csv to read (default: current log stem)")
    p.add_argument("--days-back", type=int, default=cfg["days_back"], help="only consider videos published in the last N days (default %(default)s)")
    p.add_argument("--per-query", type=int, default=cfg["per_query"], help="search results per idea, 100 quota units each (default %(default)s)")
    p.add_argument("--min-similarity", type=float, default=cfg["min_similarity"], help="(default %(default)s)")
    p.add_argument("--min-views", type=int, default=cfg["min_views"], help="strong hit = similar video with at least this many views (default %(default)s)")
    p.add_argument("--min-channels", type=int, default=cfg["min_channels"], help="repeatable = strong hits on at least this many other channels (default %(default)s)")
    p.add_argument("--limit", type=int, default=cfg["limit"] or None, help="only check the top N outliers by multiple (default: all)")
    args = p.parse_args(argv)
    args.run_id = args.run_id or current_run_id()

    folder = report_dir(args.run_id)
    src = folder / "outliers.csv"
    if not src.exists():
        sys.exit(f"{rel(src)} not found. Run `uv run python -m analysis.outliers` first (same session).")
    ideas_in = load_outliers(src)
    if args.limit:
        ideas_in = ideas_in[: args.limit]
    if not ideas_in:
        sys.exit("No outliers in this run; nothing to check.")

    published_after = (datetime.now(timezone.utc) - timedelta(days=args.days_back)).strftime("%Y-%m-%dT00:00:00Z")
    client = YouTubeClient()
    ideas, quota = [], 0
    print(f"Checking {len(ideas_in)} outlier ideas (about {100 * len(ideas_in)} quota units)...\n")
    for n, idea in enumerate(ideas_in, 1):
        try:
            r = scan_idea(client, idea, args, published_after)
        except YouTubeAPIError as e:
            print(f"  [{n}/{len(ideas_in)}] FAILED {idea['title'][:50]}: {e}", file=sys.stderr)
            if e.reason == "quotaExceeded":
                print("Daily quota exhausted; stopping. Re-run tomorrow with the same --run-id.", file=sys.stderr)
                break
            continue
        quota += 100 + 1 + max(1, (len(r["matches"]) + 49) // 50)
        ideas.append(r)
        flag = "REPEATABLE " if r["repeatable"] else "no         "
        print(f"  [{n:>2}/{len(ideas_in)}] {flag} score={r['repeatability_score']:<2} similar={r['similar_videos']:<3} {idea['title'][:60]}")

    write_markdown(folder / "repeatability.md", args, ideas, published_after, quota)
    write_csvs(folder, ideas)
    rep = [i for i in ideas if i["repeatable"]]
    print(f"\n{len(rep)} repeatable of {len(ideas)} checked.")
    print(f"report  {rel(folder / 'repeatability.md')}\ncsv     {rel(folder / 'repeatability.csv')}\nmatches {rel(folder / 'repeatability_matches.csv')}\nrun_id  {args.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
