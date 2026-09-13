"""Thin client over the YouTube Data API v3 and YouTube Analytics API v2.

Auth modes:
  * API key  (YOUTUBE_API_KEY)  -> public data: channels, videos, playlists, search, comments
  * OAuth    (`auth` command)   -> own channel (`mine=True`) and Analytics reports

Quota notes (Data API, 10,000 units/day by default):
  * list endpoints (channels, videos, playlistItems, commentThreads): 1 unit per call
  * search.list: 100 units per call -- prefer the uploads playlist for a channel's videos
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import requests

from integrations.config import settings

DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
MAX_PAGE = 50


class YouTubeAPIError(RuntimeError):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(f"YouTube API {status} [{reason}]: {message}")
        self.status = status
        self.reason = reason


class YouTubeClient:
    def __init__(self, api_key: str | None = None, oauth_token: str | None = None, timeout: int = 30):
        self.api_key = api_key if api_key is not None else settings.youtube.api_key
        self.oauth_token = oauth_token
        self.timeout = timeout
        self.session = requests.Session()
        if not self.api_key and not self.oauth_token:
            raise YouTubeAPIError(0, "noCredentials", "Set YOUTUBE_API_KEY in .env or run `auth`.")

    # ------------------------------------------------------------------ http
    def _get(self, url: str, params: dict[str, Any]) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        headers = {}
        if self.oauth_token:
            headers["Authorization"] = f"Bearer {self.oauth_token}"
        elif self.api_key:
            params["key"] = self.api_key
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                err = resp.json()["error"]
                reason = (err.get("errors") or [{}])[0].get("reason", err.get("status", "unknown"))
                message = err.get("message", resp.text)
            except (ValueError, KeyError):
                reason, message = "unknown", resp.text
            raise YouTubeAPIError(resp.status_code, reason, message)
        return resp.json()

    def _paged(self, resource: str, params: dict[str, Any], limit: int | None) -> Iterator[dict]:
        """Yield items across pages until `limit` items (None = all)."""
        fetched = 0
        page_token = None
        while True:
            page_size = MAX_PAGE if limit is None else min(MAX_PAGE, limit - fetched)
            if page_size <= 0:
                return
            data = self._get(f"{DATA_API}/{resource}", {**params, "maxResults": page_size, "pageToken": page_token})
            for item in data.get("items", []):
                yield item
                fetched += 1
                if limit is not None and fetched >= limit:
                    return
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    # ------------------------------------------------------------- channels
    def channel(self, ref: str | None = None, *, mine: bool = False) -> dict:
        """Fetch one channel by ID ("UC..."), handle ("@name"), or the authed user's own."""
        params: dict[str, Any] = {"part": "snippet,statistics,contentDetails,brandingSettings,topicDetails"}
        if mine:
            params["mine"] = "true"
        else:
            ref = ref or settings.youtube.default_channel
            if not ref:
                raise ValueError("No channel given and YOUTUBE_CHANNEL_ID / YOUTUBE_CHANNEL_HANDLE not set.")
            if ref.startswith("@"):
                params["forHandle"] = ref
            elif ref.startswith("UC") and len(ref) == 24:
                params["id"] = ref
            else:
                params["forHandle"] = "@" + ref.lstrip("@")
        items = self._get(f"{DATA_API}/channels", params).get("items", [])
        if not items:
            raise YouTubeAPIError(404, "channelNotFound", f"No channel found for {ref or 'mine'}")
        return items[0]

    def uploads_playlist_id(self, ref: str | None = None, *, mine: bool = False) -> str:
        return self.channel(ref, mine=mine)["contentDetails"]["relatedPlaylists"]["uploads"]

    # --------------------------------------------------------------- videos
    def playlist_items(
        self, playlist_id: str, limit: int | None = 50, published_after: str | None = None
    ) -> list[dict]:
        """Items in a playlist. If `published_after` (ISO date/datetime) is set, paging stops once
        items older than that appear (the uploads playlist is newest-first) and older items are dropped."""
        if not published_after:
            return list(self._paged("playlistItems", {"part": "snippet,contentDetails", "playlistId": playlist_id}, limit))
        cutoff = published_after if "T" in published_after else f"{published_after}T00:00:00Z"
        out: list[dict] = []
        for item in self._paged("playlistItems", {"part": "snippet,contentDetails", "playlistId": playlist_id}, limit):
            published = item.get("contentDetails", {}).get("videoPublishedAt") or item["snippet"]["publishedAt"]
            if published < cutoff:
                break
            out.append(item)
        return out

    def videos(self, video_ids: list[str]) -> list[dict]:
        """Full details + statistics for up to any number of video IDs (batched by 50)."""
        out: list[dict] = []
        for i in range(0, len(video_ids), MAX_PAGE):
            batch = video_ids[i : i + MAX_PAGE]
            data = self._get(
                f"{DATA_API}/videos",
                {"part": "snippet,statistics,contentDetails,status,topicDetails", "id": ",".join(batch)},
            )
            out.extend(data.get("items", []))
        return out

    def channel_videos(
        self,
        ref: str | None = None,
        *,
        mine: bool = False,
        limit: int | None = 50,
        published_after: str | None = None,
        channel: dict | None = None,
    ) -> list[dict]:
        """A channel's uploads with full stats, newest first. Cheap: ~2 units per 50 videos.

        Pass an already-fetched `channel` resource to avoid a second channels.list call.
        """
        channel = channel or self.channel(ref, mine=mine)
        playlist_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        items = self.playlist_items(playlist_id, limit, published_after=published_after)
        ids = [it["contentDetails"]["videoId"] for it in items]
        return self.videos(ids)

    def playlists(self, ref: str | None = None, *, mine: bool = False, limit: int | None = 50) -> list[dict]:
        params: dict[str, Any] = {"part": "snippet,contentDetails"}
        if mine:
            params["mine"] = "true"
        else:
            params["channelId"] = self.channel(ref)["id"]
        return list(self._paged("playlists", params, limit))

    # -------------------------------------------------------------- comments
    def comments(self, video_id: str, limit: int | None = 100, order: str = "relevance") -> list[dict]:
        return list(
            self._paged(
                "commentThreads",
                {"part": "snippet,replies", "videoId": video_id, "order": order, "textFormat": "plainText"},
                limit,
            )
        )

    # ---------------------------------------------------------------- search
    def search(
        self,
        query: str,
        *,
        kind: str = "video",
        limit: int = 25,
        channel_id: str | None = None,
        order: str = "relevance",
        published_after: str | None = None,
        published_before: str | None = None,
    ) -> list[dict]:
        """search.list costs 100 quota units per page. Use sparingly."""
        return list(
            self._paged(
                "search",
                {
                    "part": "snippet",
                    "q": query,
                    "type": kind,
                    "channelId": channel_id,
                    "order": order,
                    "publishedAfter": published_after,
                    "publishedBefore": published_before,
                },
                limit,
            )
        )

    # ------------------------------------------------------------- analytics
    def analytics(
        self,
        start_date: str,
        end_date: str,
        *,
        metrics: str = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares",
        dimensions: str | None = "day",
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
    ) -> dict:
        """YouTube Analytics report for the authed channel. Requires OAuth."""
        if not self.oauth_token:
            raise YouTubeAPIError(401, "oauthRequired", "Analytics needs OAuth. Run `auth` first.")
        return self._get(
            ANALYTICS_API,
            {
                "ids": "channel==MINE",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": metrics,
                "dimensions": dimensions,
                "filters": filters,
                "sort": sort,
                "maxResults": max_results,
            },
        )


# ------------------------------------------------------------------ helpers
_DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration_to_seconds(value: str | None) -> int | None:
    if not value:
        return None
    m = _DURATION_RE.fullmatch(value)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def flatten_video(v: dict) -> dict:
    """Compact, analysis-friendly row for a videos.list item."""
    sn, st, cd = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {})
    secs = iso_duration_to_seconds(cd.get("duration"))
    return {
        "video_id": v["id"],
        "title": sn.get("title"),
        "published_at": sn.get("publishedAt"),
        "duration_seconds": secs,
        "is_short": bool(secs is not None and secs <= 60),
        "views": int(st.get("viewCount", 0) or 0),
        "likes": int(st.get("likeCount", 0) or 0),
        "comments": int(st.get("commentCount", 0) or 0),
        "category_id": sn.get("categoryId"),
        "tags": "|".join(sn.get("tags", [])),
        "channel_id": sn.get("channelId"),
        "channel_title": sn.get("channelTitle"),
        "url": f"https://www.youtube.com/watch?v={v['id']}",
        "thumbnail": (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default") or {}).get("url"),
        "description": sn.get("description"),
    }


def flatten_channel(c: dict) -> dict:
    sn, st = c.get("snippet", {}), c.get("statistics", {})
    return {
        "channel_id": c["id"],
        "title": sn.get("title"),
        "handle": sn.get("customUrl"),
        "published_at": sn.get("publishedAt"),
        "country": sn.get("country"),
        "subscribers": int(st.get("subscriberCount", 0) or 0),
        "views": int(st.get("viewCount", 0) or 0),
        "video_count": int(st.get("videoCount", 0) or 0),
        "uploads_playlist": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "description": sn.get("description"),
    }


def flatten_comment(t: dict) -> dict:
    top = t["snippet"]["topLevelComment"]["snippet"]
    return {
        "comment_id": t["id"],
        "video_id": t["snippet"].get("videoId"),
        "author": top.get("authorDisplayName"),
        "published_at": top.get("publishedAt"),
        "likes": int(top.get("likeCount", 0) or 0),
        "reply_count": int(t["snippet"].get("totalReplyCount", 0) or 0),
        "text": top.get("textDisplay"),
    }


def flatten_search(s: dict) -> dict:
    sn, ident = s.get("snippet", {}), s.get("id", {})
    kind = ident.get("kind", "").split("#")[-1]
    ref_id = ident.get("videoId") or ident.get("channelId") or ident.get("playlistId")
    return {
        "kind": kind,
        "id": ref_id,
        "title": sn.get("title"),
        "channel_id": sn.get("channelId"),
        "channel_title": sn.get("channelTitle"),
        "published_at": sn.get("publishedAt"),
        "description": sn.get("description"),
    }


def flatten_analytics(report: dict) -> list[dict]:
    cols = [c["name"] for c in report.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in report.get("rows", [])]
