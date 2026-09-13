from analysis.outliers import analyze_channel


def vid(i, views, days, fmt="long"):
    return {"video_id": f"v{i}", "title": f"t{i}", "views": views, "days_live": days, "format": fmt}


def test_outlier_uses_median_of_mature_videos_only():
    vids = [vid(1, 100, 30), vid(2, 100, 30), vid(3, 100, 30), vid(4, 350, 30), vid(5, 5000, 2)]
    r = analyze_channel("c", vids, threshold=3.0, min_age=7, formats=["long"])
    g = r["groups"]["long"]
    assert g["median"] == 100 and g["n_mature"] == 4
    by_id = {v["video_id"]: v for v in g["videos"]}
    assert by_id["v4"]["is_outlier"] and by_id["v4"]["multiple"] == 3.5
    assert not by_id["v5"]["is_outlier"] and by_id["v5"]["note"] == "too new"


def test_thin_baseline_flag_and_shorts_separation():
    vids = [vid(1, 10, 30), vid(2, 20, 30), vid(3, 1000, 30, "short")]
    r = analyze_channel("c", vids, threshold=3.0, min_age=7, formats=["long", "short"])
    assert r["groups"]["long"]["thin"] and r["groups"]["short"]["n_total"] == 1
    assert r["groups"]["long"]["median"] == 15
