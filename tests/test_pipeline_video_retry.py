import os
import stat
from pathlib import Path

from analysis import pipeline


def test_video_step_resumes_until_mp4_exists(tmp_path, monkeypatch):
    # fake agent dir + fake launcher that only "delivers" on its 2nd call, and records the resume note it got
    agent = tmp_path / "agent"; (agent / "output").mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    launcher = tmp_path / "launch.sh"
    launcher.write_text(f'''#!/bin/bash
echo "$3" >> "{calls}"
n=$(wc -l < "{calls}")
if [ "$n" -ge 2 ]; then mkdir -p "{agent}/output/run1__vid" && echo x > "{agent}/output/run1__vid/video.mp4"; fi
exit 0
''')
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(pipeline.pipeline_config, "section", lambda name: {"agent_dir": str(agent)} if name == "video" else {})
    monkeypatch.setattr(pipeline.progress, "log", lambda *a, **k: None)
    rc = pipeline.run_video("run1", "run1__vid.md", [str(launcher)])
    notes = calls.read_text().splitlines()
    assert rc == 0 and len(notes) == 2 and notes[0] == "" and notes[1].startswith("RESUME:")


def test_video_step_gives_up_after_attempts(tmp_path, monkeypatch):
    agent = tmp_path / "agent"; (agent / "output").mkdir(parents=True)
    launcher = tmp_path / "launch.sh"; launcher.write_text("#!/bin/bash\nexit 0\n"); launcher.chmod(0o755)
    monkeypatch.setattr(pipeline.pipeline_config, "section", lambda name: {"agent_dir": str(agent)} if name == "video" else {})
    logged = []
    monkeypatch.setattr(pipeline.progress, "log", lambda step, msg, run_id=None, **k: logged.append(msg))
    assert pipeline.run_video("run1", "run1__vid.md", [str(launcher)]) == 1
    assert any("giving up" in m for m in logged)
