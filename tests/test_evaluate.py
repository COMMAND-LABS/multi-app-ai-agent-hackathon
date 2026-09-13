from analysis.evaluate import ffprobe


def test_ffprobe_handles_missing_file(tmp_path):
    assert ffprobe(tmp_path / "nope.mp4") in ({}, {"duration": 0.0, "width": None, "height": None, "audio": False})
