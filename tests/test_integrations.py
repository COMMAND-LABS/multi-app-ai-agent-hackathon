import json
from pathlib import Path
from unittest.mock import MagicMock

from integrations.airtable import AirtableClient
from integrations.airtable.push import MERGE_ON, to_record
from integrations.metricool.client import build_post


def test_airtable_record_shape_and_evidence():
    idea = {"idea_title": "T", "found_at": "2026-09-13T00:00:00+00:00", "repeatable": "True", "source_channel": "x", "source_video_id": "v1",
            "source_url": "u", "source_views": "100", "outlier_multiple": "3.5", "topic_query": "q", "repeatability_score": "4",
            "similar_videos": "5", "strong_hits": "4", "median_match_views": "200", "description": "d"}
    matches = [{"strong_hit": "True", "match_channel": "c", "match_views": "999", "match_title": "m", "url": "u2"}]
    r = to_record(idea, matches, "run1")
    assert r["Run ID"] == "run1" and r["Repeatable"] is True and r["Outlier Multiple"] == 3.5 and "✔ c — 999 views" in r["Evidence"]
    assert MERGE_ON == ["Run ID", "Source Video ID"]


def test_airtable_upsert_batches_of_ten(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "x"); monkeypatch.setenv("AIRTABLE_BASE_ID", "appX")
    c = AirtableClient(api_key="x", base_id="appX")
    calls = []
    def fake(method, url, timeout=None, **kw):
        calls.append(kw["json"]); r = MagicMock(); r.status_code = 200; r.content = b"1"
        r.json.return_value = {"records": [{"id": "r", "fields": {}} for _ in kw["json"]["records"]], "createdRecords": ["r"] * len(kw["json"]["records"]), "updatedRecords": []}
        return r
    c.session.request = fake
    res = c.upsert("T", [{"Idea": str(i), "Run ID": "r", "Source Video ID": str(i)} for i in range(23)], MERGE_ON)
    assert len(calls) == 3 and len(res["created"]) == 23 and calls[0]["performUpsert"]["fieldsToMergeOn"] == MERGE_ON


def test_metricool_payload_matches_connector_schema():
    info = build_post("hello", "https://x/v.mp4", ["instagram", "youtube"], "2026-09-14T10:00:00", "America/New_York",
                      draft=True, auto_publish=True, title="My title", declare_ai=True, instagram_type="REEL", youtube_privacy="private", tags=["a"])
    assert info["providers"] == [{"network": "instagram"}, {"network": "youtube"}]
    assert info["media"] == ["https://x/v.mp4"] and info["draft"] is True
    assert info["publicationDate"] == {"dateTime": "2026-09-14T10:00:00", "timezone": "America/New_York"}
    assert info["instagramData"]["type"] == "REEL" and info["youtubeData"]["type"] == "short" and info["youtubeData"]["privacy"] == "private"
    assert "tiktokData" not in info
