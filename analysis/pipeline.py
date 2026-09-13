"""Run the whole pipeline, or a slice of it, in order — one command, one progress log.

    uv run python -m analysis.pipeline                 # all 8 steps
    uv run python -m analysis.pipeline --from outliers --to airtable
    uv run python -m analysis.pipeline --skip video    # everything except the (slow) video build
    uv run python -m analysis.pipeline --only evaluate

Steps: pull, outliers, repeatability, airtable, handoff, video, gcs, metricool, evaluate.
Stops at the first failing step. Every step appends to logs/progress.log; every artifact shares run_id.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta

from analysis import config as pipeline_config
from analysis import progress
from analysis.run import current_run_id
from integrations.config import PROJECT_ROOT

STEPS = ["pull", "outliers", "repeatability", "airtable", "handoff", "video", "gcs", "metricool", "evaluate"]


def commands(run_id: str, dry: bool) -> dict[str, list[str]]:
    cfg = pipeline_config.load()
    since = (date.today() - timedelta(days=cfg["pull"]["days"])).isoformat()
    uv = ["uv", "run", "python", "-m"]
    return {
        "pull": uv + ["integrations.youtube", "pull-all"],
        "outliers": uv + ["analysis.outliers", "--window", f"since_{since}", "--run-id", run_id],
        "repeatability": uv + ["analysis.repeatability", "--run-id", run_id],
        "airtable": uv + ["integrations.airtable.push", "--run-id", run_id] + (["--dry-run"] if dry else []),
        "handoff": uv + ["analysis.handoff", "--run-id", run_id],
        "video": [str(PROJECT_ROOT / "scripts" / "run_video_agent.sh"), "__LATEST_BRIEF__"],
        "gcs": uv + ["integrations.gcs.upload", "--run-id", run_id] + (["--dry-run"] if dry else []),
        "metricool": uv + ["integrations.metricool.schedule", "--run-id", run_id] + (["--dry-run"] if dry else []),
        "evaluate": uv + ["analysis.evaluate", "--run-id", run_id],
    }


RESUME_NOTE = ("RESUME: a previous session ended before delivering. The HyperFrames project for this brief may "
               "already exist under videos/ — do NOT re-init it. Inspect what is on disk (BRIEF.md, frame.md, "
               "STORYBOARD.md, SCRIPT.md, audio_meta.json, assets/voice, assets/bgm, compositions/frames, renders) "
               "and continue from the first missing artifact, running every command in the FOREGROUND, until "
               "output/<brief-id>/video.mp4 and SUMMARY.md exist.")
VIDEO_ATTEMPTS = 3


def run_video(run_id: str, brief: str, launcher: list[str]) -> int:
    """Run the video sub-agent until its deliverable exists. The agent's exit code is not trusted:
    a headless session can end cleanly without finishing, so we check the MP4 and resume if needed."""
    agent_dir = (PROJECT_ROOT / pipeline_config.section("video")["agent_dir"]).resolve()
    video = agent_dir / "output" / brief[:-3] / "video.mp4"
    for attempt in range(1, VIDEO_ATTEMPTS + 1):
        note = "" if attempt == 1 else RESUME_NOTE
        progress.log("pipeline", f"video attempt {attempt}/{VIDEO_ATTEMPTS}" + (" (resume)" if note else ""), run_id)
        subprocess.call(launcher + [brief, "", note], cwd=PROJECT_ROOT)
        if video.exists():
            progress.log("pipeline", f"video delivered: {video.relative_to(agent_dir)}", run_id)
            return 0
        progress.log("pipeline", f"video attempt {attempt} ended without {video.name}; " + ("resuming" if attempt < VIDEO_ATTEMPTS else "giving up"), run_id)
    return 1


def latest_brief(run_id: str) -> str | None:
    agent_dir = (PROJECT_ROOT / pipeline_config.section("video")["agent_dir"]).resolve()
    briefs = sorted((agent_dir / "briefs").glob(f"{run_id}__*.md"), key=lambda p: p.stat().st_mtime)
    return briefs[-1].name if briefs else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m analysis.pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0])
    p.add_argument("--to", dest="end", choices=STEPS, default=STEPS[-1])
    p.add_argument("--only", choices=STEPS)
    p.add_argument("--skip", nargs="*", choices=STEPS, default=[])
    p.add_argument("--run-id")
    p.add_argument("--dry-run", action="store_true", help="airtable/gcs/metricool in dry-run mode (no external writes)")
    args = p.parse_args(argv)
    # A full pipeline run gets its own fresh run id (a slice with --from/--only reuses the current one unless given).
    run_id = args.run_id or (datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_pipeline" if args.start == STEPS[0] and not args.only else current_run_id())
    todo = [args.only] if args.only else STEPS[STEPS.index(args.start): STEPS.index(args.end) + 1]
    todo = [s for s in todo if s not in args.skip]
    cmds = commands(run_id, args.dry_run)

    progress.log("pipeline", f"START steps={','.join(todo)}{' (dry-run)' if args.dry_run else ''}", run_id)
    print(f"run_id {run_id}\nsteps  {' → '.join(todo)}\n")
    for step in todo:
        cmd = cmds[step]
        if step == "video":
            brief = latest_brief(run_id)
            if not brief:
                progress.log("pipeline", "video: no brief for this run; skipping", run_id); print("video: no brief, skipping"); continue
            print(f"=== video: {cmd[0]} {brief}  (up to {VIDEO_ATTEMPTS} attempts, judged by the MP4)")
            progress.log("pipeline", "→ video", run_id)
            rc = run_video(run_id, brief, [cmd[0]])
        else:
            print(f"=== {step}: {' '.join(cmd)}")
            progress.log("pipeline", f"→ {step}", run_id)
            rc = subprocess.call(cmd, cwd=PROJECT_ROOT)
        if rc != 0:
            progress.log("pipeline", f"STOP: {step} exited {rc}", run_id)
            print(f"\npipeline stopped: {step} exited {rc}", file=sys.stderr)
            return rc
    progress.log("pipeline", f"DONE steps={','.join(todo)}", run_id)
    print("\npipeline done. progress: logs/progress.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
