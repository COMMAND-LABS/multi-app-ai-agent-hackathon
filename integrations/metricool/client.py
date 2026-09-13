"""Minimal Metricool scheduler client (X-Mc-Auth user token from .env).

Endpoints used (Metricool public API v2):
  POST   /api/v2/scheduler/posts?userId=&blogId=          create a scheduled post (draft or live)
  GET    /api/v2/scheduler/posts?userId=&blogId=&start=&end=&timezone=   list scheduled posts
  DELETE /api/v2/scheduler/posts/{id}?userId=&blogId=     delete one
"""

from __future__ import annotations

from typing import Any

import requests

from integrations.config import settings

API = "https://app.metricool.com/api/v2"


class MetricoolAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Metricool API {status}: {message}")
        self.status = status


class MetricoolClient:
    def __init__(self, user_token: str | None = None, user_id: str | None = None, blog_id: str | None = None, timeout: int = 30):
        m = settings.metricool
        self.token = user_token if user_token is not None else m.user_token
        self.user_id = user_id if user_id is not None else m.user_id
        self.blog_id = blog_id if blog_id is not None else m.blog_id
        missing = [n for n, v in (("METRICOOL_USER_TOKEN", self.token), ("METRICOOL_USER_ID", self.user_id), ("METRICOOL_BLOG_ID", self.blog_id)) if not v]
        if missing:
            raise MetricoolAPIError(0, f"missing in .env: {', '.join(missing)}")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Mc-Auth": self.token, "Content-Type": "application/json", "Accept": "application/json"})

    def _req(self, method: str, path: str, **kw) -> Any:
        params = {"userId": self.user_id, "blogId": self.blog_id, **kw.pop("params", {})}
        r = self.session.request(method, f"{API}{path}", params=params, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            try:
                msg = r.json()
            except ValueError:
                msg = r.text
            raise MetricoolAPIError(r.status_code, str(msg)[:500])
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {"raw": r.text}

    def create_post(self, info: dict) -> dict:
        return self._req("POST", "/scheduler/posts", json=info)

    def list_posts(self, start: str, end: str, timezone: str) -> list[dict]:
        data = self._req("GET", "/scheduler/posts", params={"start": start, "end": end, "timezone": timezone})
        return data.get("data", data) if isinstance(data, dict) else data

    def delete_post(self, post_id: str | int) -> Any:
        return self._req("DELETE", f"/scheduler/posts/{post_id}")


# ---------------------------------------------------------------- payloads
NETWORK_DATA = {
    "instagram": lambda c: {"instagramData": {"type": c.get("instagram_type", "REEL"), "showReelOnFeed": True, "isAiGenerated": c.get("declare_ai", True)}},
    "tiktok":    lambda c: {"tiktokData": {"privacyOption": c.get("tiktok_privacy", "SELF_ONLY"), "isAigc": c.get("declare_ai", True), "title": c.get("title", "")[:90]}},
    "youtube":   lambda c: {"youtubeData": {"title": c.get("title", "")[:100], "type": "short", "privacy": c.get("youtube_privacy", "private"), "madeForKids": False, "isAiGeneratedContent": c.get("declare_ai", True), "tags": c.get("tags", [])}},
    "facebook":  lambda c: {"facebookData": {"type": "REEL", "title": c.get("title", "")[:100]}},
    "linkedin":  lambda c: {"linkedinData": {"type": "post", "previewIncluded": True}},
    "twitter":   lambda c: {"twitterData": {"tags": []}},
    "threads":   lambda c: {"threadsData": {"allowedCountryCodes": []}},
    "bluesky":   lambda c: {"blueskyData": {"postLanguages": ["en"]}},
}


def build_post(text: str, media_url: str, networks: list[str], when_local: str, timezone: str, *, draft: bool, auto_publish: bool, **net_opts) -> dict:
    """Assemble the scheduler payload in the shape Metricool expects (see the connector schema)."""
    info: dict[str, Any] = {
        "text": text,
        "publicationDate": {"dateTime": when_local, "timezone": timezone},
        "providers": [{"network": n} for n in networks],
        "media": [media_url],
        "mediaAltText": [],
        "autoPublish": auto_publish,
        "draft": draft,
        "descendants": [],
        "firstCommentText": "",
        "hasNotReadNotes": False,
        "shortener": False,
        "smartLinkData": {"ids": []},
    }
    for n in networks:
        if n in NETWORK_DATA:
            info.update(NETWORK_DATA[n](net_opts))
    return info
