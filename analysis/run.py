"""Run identity: every analysis step writes into reports/<run_id>/ where run_id matches the
current session's tool-call log stem (logs/<date>_<time>_<session>.log), so a run's log and its
reports share one name."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from integrations.config import PROJECT_ROOT

LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"


def current_run_id() -> str:
    """Stem of logs/latest.log if the tool-call hook is active, else a fresh timestamp."""
    override = os.environ.get("RUN_ID")
    if override:
        return override
    latest = LOGS_DIR / "latest.log"
    if latest.is_symlink() or latest.exists():
        try:
            return Path(os.readlink(latest)).stem if latest.is_symlink() else latest.stem
        except OSError:
            pass
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_manual"


def report_dir(run_id: str | None = None) -> Path:
    run_id = run_id or current_run_id()
    d = REPORTS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
