---
name: youtube
description: Pull YouTube channel, video, comment, search, playlist, and analytics data via the project's YouTube Data/Analytics API client. Use when the user asks to fetch, pull, refresh, analyze, or compare YouTube data, or when another integration (Airtable, Metricool) needs YouTube numbers as input.
---

# YouTube integration

All commands run from the project root and write results to `data/youtube/<channel>/<kind>/`.

```bash
uv run python -m integrations.youtube <command> [options]
```

## Before pulling anything

1. Run `uv run python -m integrations.youtube check`. It reports whether `.env` exists, whether the API key / OAuth token are present, and does one live call against the default channel.
2. If the API key is missing, stop and tell the user to fill `YOUTUBE_API_KEY` in `.env` (see `.env.example`). Never ask the user to paste secrets into chat.
3. For `--mine` or `analytics`, an OAuth token must exist. If not, tell the user to run `uv run python -m integrations.youtube auth` themselves (it opens a browser).

## Commands

| Command | What it pulls | Auth | Quota cost |
|---|---|---|---|
| `channel [ID or @handle] [--mine]` | Profile, subscriber/view/video counts, uploads playlist ID | key or OAuth | 1 |
| `videos [ID or @handle] [--days N \| --since YYYY-MM-DD \| --max N \| --all] [--mine]` | Uploads with views/likes/comments/duration, newest first. Also saves the channel profile. | key or OAuth | ~2 per 50 videos |
| `video ID [ID ...]` | Full details for specific videos | key | 1 per 50 |
| `comments VIDEO_ID [--max N] [--all] [--order time] [--channel @handle]` | Top-level comment threads with replies | key | 1 per 100 |
| `search "query" [--type video] [--max N] [--channel-id] [--order] [--after] [--before]` | Search results | key | **100 per 50 results** |
| `playlists [ID or @handle] [--mine]` | Channel playlists | key or OAuth | 1 |
| `playlist-items PLAYLIST_ID [--all]` | Videos inside a playlist with stats | key | ~2 per 50 |
| `analytics [--days 28] [--start] [--end] [--dimensions day] [--metrics ...] [--filters] [--sort]` | Owner-only analytics (watch time, retention, subs) | OAuth | Analytics API, separate quota |
| `auth` | Runs OAuth consent flow, caches token | — | — |

Global flags: `--json` (machine-readable stdout), `--no-save` (skip writing files).

The channel argument is optional; it falls back to `YOUTUBE_CHANNEL_ID` / `YOUTUBE_CHANNEL_HANDLE` from `.env`.

## Data layout

One folder per channel, named by handle (lowercase, no `@`). Data not tied to a channel goes under `_global/`.

```
data/youtube/
  <handle>/
    channel/   <timestamp>_profile.json + .csv, latest_profile.json/.csv   (subs, views, video count)
    videos/    <timestamp>_since_<date>.json + .csv   (or _last_<N> / _all), latest_* copies
    comments/  <timestamp>_<video_id>.json + .csv     (only if --channel was passed)
    playlists/ ...
  _global/
    search/    <timestamp>_<query>.json + .csv
    videos/    ad-hoc `video ID ...` lookups
    comments/  comments pulled without --channel
    analytics/ owner analytics reports (OAuth)
```

Each JSON file is an envelope: `{pulled_at, kind, name, channel, count, ..., data}` where `data` is the raw API response items. Video pulls also record `published_after` and `limit`. The CSV is the flattened, analysis-ready table (see `flatten_*` in `integrations/youtube/client.py`). `latest_*` files are always the most recent pull for that name, so read those for "current" numbers and compare timestamped files for change over time.

To pull a set of channels for a window, loop the command:

```bash
for h in @a @b @c; do uv run python -m integrations.youtube videos "$h" --days 30; done
```

## Working guidance

- Prefer `videos` over `search` to list a channel's content. `search` is 100x more expensive on quota (10,000 units/day default).
- `videos` gives `is_short` (duration ≤ 60s) so Shorts vs long-form can be split.
- Analyze with the CSVs (pandas is not installed by default; `csv`/`json` from stdlib or add pandas via `uv add pandas` if the user wants heavier analysis).
- When an error says `quotaExceeded`, do not retry; report it. Quota resets at midnight Pacific.
- `keyInvalid` / `accessNotConfigured` mean the key is wrong or YouTube Data API v3 is not enabled on the Google Cloud project.
- Subscriber counts from the public API are rounded (3 significant figures). Exact numbers need `--mine` with OAuth.
- The client is importable for ad-hoc scripts:

```python
from integrations.youtube import YouTubeClient
from integrations.youtube.client import flatten_video
client = YouTubeClient()
rows = [flatten_video(v) for v in client.channel_videos("@handle", published_after="2026-08-01")]
```

## Step 2: outlier multiples

```bash
uv run python -m analysis.outliers [--window since_2026-06-15] [--channels @a @b] [--threshold 3] [--min-age-days 7] [--format long|short|both]
```

Reads each channel's `latest_<window>.csv`, computes `multiple = views / channel median` (per format, mature videos only), and writes `reports/<run_id>/outliers.md` (human report) and `outliers.csv` (one row per video, with `run_id`, `multiple`, `is_outlier`, `title`, `description`, `url`). The `run_id` equals the current tool-call log stem (`logs/latest.log`), so a run's log and reports share one name. Downstream steps (repeatability, Airtable) read `outliers.csv` and carry `run_id` through so everything from one run can be tied together.
