from integrations.youtube.client import flatten_channel, flatten_video, iso_duration_to_seconds


def test_iso_duration():
    assert iso_duration_to_seconds("PT1M30S") == 90
    assert iso_duration_to_seconds("P1DT2H3M4S") == 93784
    assert iso_duration_to_seconds("PT0S") == 0
    assert iso_duration_to_seconds(None) is None


def test_flatten_video_marks_shorts():
    v = {"id": "x", "snippet": {"title": "T", "publishedAt": "2026-01-01T00:00:00Z", "tags": ["a"], "thumbnails": {}},
         "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "1"}, "contentDetails": {"duration": "PT45S"}}
    r = flatten_video(v)
    assert r["is_short"] and r["duration_seconds"] == 45 and r["views"] == 10 and r["url"].endswith("v=x")


def test_flatten_channel_counts():
    c = {"id": "UC1", "snippet": {"title": "A", "customUrl": "@a"}, "statistics": {"subscriberCount": "1200", "viewCount": "5", "videoCount": "3"},
         "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}
    assert flatten_channel(c)["subscribers"] == 1200 and flatten_channel(c)["uploads_playlist"] == "UU1"
