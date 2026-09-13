"""CLI for pulling YouTube data.

    uv run python -m integrations.youtube <command> [options]

Every command prints a short summary and writes results under data/youtube/<kind>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from integrations.config import ENV_FILE, settings
from integrations.youtube import auth
from integrations.youtube.client import (
    YouTubeAPIError,
    YouTubeClient,
    flatten_analytics,
    flatten_channel,
    flatten_comment,
    flatten_search,
    flatten_video,
)
from integrations.youtube.storage import rel, save


def _client(use_oauth: bool) -> YouTubeClient:
    token = auth.access_token() if use_oauth or not settings.youtube.has_api_key else None
    if use_oauth and not token:
        sys.exit("OAuth token missing or expired. Run: uv run python -m integrations.youtube auth")
    return YouTubeClient(oauth_token=token)


def _report(written: dict, summary: list[dict], args) -> None:
    if not args.no_save:
        for label, path in written.items():
            print(f"saved {label:10s} {rel(path)}", file=sys.stderr)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        for row in summary:
            print(row)


# ------------------------------------------------------------------ commands
def cmd_check(args) -> None:
    yt = settings.youtube
    print(f".env file      : {'found' if ENV_FILE.exists() else 'MISSING (copy .env.example to .env)'}")
    print(f"API key        : {'set' if yt.has_api_key else 'not set'}")
    print(f"OAuth client   : {'set' if yt.has_oauth_client else 'not set'}")
    print(f"OAuth token    : {'cached at ' + rel(yt.token_file) if yt.has_token else 'none'}")
    print(f"Default channel: {yt.default_channel or 'not set'}")
    print(f"Data dir       : {settings.data_dir}")
    if yt.has_api_key and yt.default_channel:
        try:
            c = flatten_channel(YouTubeClient().channel())
            print(f"Live check     : OK -> {c['title']} ({c['subscribers']:,} subs, {c['video_count']:,} videos)")
        except YouTubeAPIError as e:
            print(f"Live check     : FAILED -> {e}")


def cmd_auth(args) -> None:
    path = auth.run_auth_flow()
    print(f"Token saved to {rel(path)}")


def _channel_key(flat: dict) -> str:
    return flat["handle"] or flat["channel_id"]


def cmd_channel(args) -> None:
    c = _client(args.mine).channel(args.channel, mine=args.mine)
    flat = flatten_channel(c)
    written = {} if args.no_save else save("channel", "profile", c, [flat], channel=_channel_key(flat))
    _report(written, [flat], args)


def cmd_videos(args) -> None:
    client = _client(args.mine)
    c = client.channel(args.channel, mine=args.mine)
    flat = flatten_channel(c)
    key = _channel_key(flat)
    since = args.since or ((date.today() - timedelta(days=args.days)).isoformat() if args.days else None)
    limit = None if (args.all or since) else args.max
    vids = client.channel_videos(mine=args.mine, limit=limit, published_after=since, channel=c)
    rows = [flatten_video(v) for v in vids]
    name = f"since_{since}" if since else ("all" if args.all else f"last_{args.max}")
    written = {}
    if not args.no_save:
        save("channel", "profile", c, [flat], channel=key)
        written = save("videos", name, vids, rows, channel=key, meta={"published_after": since, "limit": limit})
    print(f"{flat['title']} ({key}): {len(rows)} videos" + (f" since {since}" if since else ""), file=sys.stderr)
    summary = [{k: r[k] for k in ("video_id", "title", "published_at", "views", "likes", "comments", "duration_seconds")} for r in rows]
    _report(written, summary, args)


def cmd_video(args) -> None:
    vids = _client(False).videos(args.ids)
    rows = [flatten_video(v) for v in vids]
    written = {} if args.no_save else save("videos", "_".join(args.ids[:3]), vids, rows)
    _report(written, rows, args)


def cmd_comments(args) -> None:
    threads = _client(False).comments(args.video_id, limit=None if args.all else args.max, order=args.order)
    rows = [flatten_comment(t) for t in threads]
    channel = args.channel
    written = {} if args.no_save else save("comments", args.video_id, threads, rows, channel=channel)
    _report(written, rows, args)


def cmd_search(args) -> None:
    results = _client(False).search(
        args.query,
        kind=args.type,
        limit=args.max,
        channel_id=args.channel_id,
        order=args.order,
        published_after=args.after,
        published_before=args.before,
    )
    rows = [flatten_search(r) for r in results]
    written = {} if args.no_save else save("search", args.query, results, rows)
    _report(written, rows, args)


def cmd_playlists(args) -> None:
    pls = _client(args.mine).playlists(args.channel, mine=args.mine, limit=None if args.all else args.max)
    rows = [
        {
            "playlist_id": p["id"],
            "title": p["snippet"]["title"],
            "item_count": p.get("contentDetails", {}).get("itemCount"),
            "published_at": p["snippet"].get("publishedAt"),
        }
        for p in pls
    ]
    name = args.channel or ("mine" if args.mine else settings.youtube.default_channel)
    written = {} if args.no_save else save("playlists", "all", pls, rows, channel=name)
    _report(written, rows, args)


def cmd_playlist_items(args) -> None:
    client = _client(False)
    items = client.playlist_items(args.playlist_id, limit=None if args.all else args.max)
    vids = client.videos([i["contentDetails"]["videoId"] for i in items])
    rows = [flatten_video(v) for v in vids]
    written = {} if args.no_save else save("playlists", args.playlist_id, vids, rows)
    _report(written, [{k: r[k] for k in ("video_id", "title", "views", "published_at")} for r in rows], args)


def cmd_analytics(args) -> None:
    end = args.end or date.today().isoformat()
    start = args.start or (date.fromisoformat(end) - timedelta(days=args.days)).isoformat()
    report = _client(True).analytics(
        start,
        end,
        metrics=args.metrics,
        dimensions=args.dimensions or None,
        filters=args.filters,
        sort=args.sort,
        max_results=args.max,
    )
    rows = flatten_analytics(report)
    written = {} if args.no_save else save("analytics", f"{args.dimensions or 'total'}_{start}_{end}", report, rows)
    _report(written, rows, args)


def cmd_pull_all(args) -> None:
    """Step 1: pull every channel listed in pipeline.toml for the configured window."""
    from analysis import config as pipeline_config

    handles = args.channels or pipeline_config.section("channels")["handles"]
    days = args.days or pipeline_config.section("pull")["days"]
    if not handles:
        sys.exit("No channels: add them under [channels] in pipeline.toml or pass them on the command line.")
    since = (date.today() - timedelta(days=days)).isoformat()
    client = _client(False)
    print(f"Pulling {len(handles)} channels since {since} ({days} days)", file=sys.stderr)
    for h in handles:
        c = client.channel(h)
        flat = flatten_channel(c)
        key = _channel_key(flat)
        vids = client.channel_videos(limit=None, published_after=since, channel=c)
        rows = [flatten_video(v) for v in vids]
        if not args.no_save:
            save("channel", "profile", c, [flat], channel=key)
            written = save("videos", f"since_{since}", vids, rows, channel=key, meta={"published_after": since, "limit": None})
            print(f"  {flat['title']:<35} {len(rows):>4} videos -> {rel(written['latest_csv'])}", file=sys.stderr)
        else:
            print(f"  {flat['title']:<35} {len(rows):>4} videos", file=sys.stderr)
    print(f"\nwindow  since_{since}   (use this with: uv run python -m analysis.outliers --window since_{since})", file=sys.stderr)


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m integrations.youtube", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="print summary as JSON instead of Python rows")
    p.add_argument("--no-save", action="store_true", help="do not write files under data/")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="show config status and do a live API call").set_defaults(fn=cmd_check)
    sub.add_parser("auth", help="run the OAuth consent flow (needed for --mine and analytics)").set_defaults(fn=cmd_auth)

    def channel_args(sp):
        sp.add_argument("channel", nargs="?", help="channel ID (UC...) or @handle; defaults to .env")
        sp.add_argument("--mine", action="store_true", help="use the OAuth-authed channel")

    s = sub.add_parser("channel", help="channel profile + statistics"); channel_args(s); s.set_defaults(fn=cmd_channel)

    s = sub.add_parser("videos", help="a channel's uploads with stats (newest first)")
    channel_args(s)
    s.add_argument("--max", type=int, default=50, help="max videos when no date window is given")
    s.add_argument("--all", action="store_true", help="fetch every upload")
    s.add_argument("--days", type=int, help="only videos published in the last N days")
    s.add_argument("--since", help="only videos published on/after YYYY-MM-DD")
    s.set_defaults(fn=cmd_videos)

    s = sub.add_parser("pull-all", help="step 1: pull every channel in pipeline.toml for the configured window")
    s.add_argument("channels", nargs="*", help="override the channel list")
    s.add_argument("--days", type=int, help="override [pull] days")
    s.set_defaults(fn=cmd_pull_all)

    s = sub.add_parser("video", help="details for specific video IDs")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_video)

    s = sub.add_parser("comments", help="top-level comment threads for a video")
    s.add_argument("video_id")
    s.add_argument("--max", type=int, default=100)
    s.add_argument("--all", action="store_true")
    s.add_argument("--order", choices=["relevance", "time"], default="relevance")
    s.add_argument("--channel", help="@handle to file the comments under (optional)")
    s.set_defaults(fn=cmd_comments)

    s = sub.add_parser("search", help="search YouTube (100 quota units per 50 results)")
    s.add_argument("query")
    s.add_argument("--type", choices=["video", "channel", "playlist"], default="video")
    s.add_argument("--max", type=int, default=25)
    s.add_argument("--channel-id", help="restrict to a channel ID")
    s.add_argument("--order", choices=["relevance", "date", "viewCount", "rating", "title"], default="relevance")
    s.add_argument("--after", help="RFC3339, e.g. 2026-01-01T00:00:00Z")
    s.add_argument("--before", help="RFC3339")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("playlists", help="a channel's playlists")
    channel_args(s)
    s.add_argument("--max", type=int, default=50)
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_playlists)

    s = sub.add_parser("playlist-items", help="videos (with stats) inside a playlist")
    s.add_argument("playlist_id")
    s.add_argument("--max", type=int, default=50)
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_playlist_items)

    s = sub.add_parser("analytics", help="YouTube Analytics report for your channel (OAuth)")
    s.add_argument("--start", help="YYYY-MM-DD (default: --days before end)")
    s.add_argument("--end", help="YYYY-MM-DD (default: today)")
    s.add_argument("--days", type=int, default=28)
    s.add_argument("--metrics", default="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares")
    s.add_argument("--dimensions", default="day", help="e.g. day, video, country, trafficSource; '' for totals")
    s.add_argument("--filters", help="e.g. video==VIDEO_ID")
    s.add_argument("--sort", help="e.g. -views")
    s.add_argument("--max", type=int)
    s.set_defaults(fn=cmd_analytics)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except YouTubeAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        if e.reason == "quotaExceeded":
            print("hint: daily quota is spent; it resets at midnight Pacific.", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
