"""The ONE progress log: logs/progress.log. Every pipeline step and both agents append plain lines here.

    uv run python -m analysis.progress [-n 40] [--run-id X] [-f]     # show / follow it

Line format (fixed columns, grep-friendly):
    2026-09-13 15:31:02  <run_id>  <actor>  <step>  <message>
actor = pipeline | main-agent | video-agent.  Secrets are redacted by the tool-call logger; step code
never logs credential values.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from integrations.config import PROJECT_ROOT

PROGRESS_LOG = Path(os.environ.get("PIPELINE_PROGRESS_LOG") or PROJECT_ROOT / "logs" / "progress.log")


def log(step: str, message: str, run_id: str | None = None, actor: str = "pipeline") -> str:
    if run_id is None:
        from analysis.run import current_run_id
        run_id = current_run_id()
    PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {run_id:<28}  {actor:<11}  {step:<13}  {message}"
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def lines(run_id: str | None = None, n: int | None = None) -> list[str]:
    if not PROGRESS_LOG.exists():
        return []
    out = [l.rstrip("\n") for l in PROGRESS_LOG.read_text(encoding="utf-8").splitlines()]
    if run_id:
        out = [l for l in out if f"  {run_id} " in l or f"  {run_id}  " in l]
    return out[-n:] if n else out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m analysis.progress", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-n", type=int, default=40)
    p.add_argument("--run-id")
    p.add_argument("-f", action="store_true", help="follow (tail -f)")
    args = p.parse_args(argv)
    if args.f:
        PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True); PROGRESS_LOG.touch()
        return subprocess.call(["tail", "-n", str(args.n), "-f", str(PROGRESS_LOG)])
    print("\n".join(lines(args.run_id, args.n)) or f"(empty: {PROGRESS_LOG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
