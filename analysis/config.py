"""Pipeline settings from pipeline.toml (non-secret knobs). Secrets stay in .env.

    uv run python -m analysis.config        # print the effective settings

Each section is returned as a plain dict with defaults filled in, so a missing key in the file
never breaks a step. CLI flags in each step override these values for a single run.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from integrations.config import PROJECT_ROOT

CONFIG_FILE = PROJECT_ROOT / "pipeline.toml"

DEFAULTS: dict[str, dict] = {
    "channels": {"handles": []},
    "pull": {"days": 90},
    "outliers": {"threshold": 3.0, "min_age_days": 7, "format": "long"},
    "repeatability": {"days_back": 180, "per_query": 25, "min_similarity": 0.4, "min_views": 10_000, "min_channels": 3, "limit": 0},
    "airtable": {"table": "Repeatable Ideas", "push_all": False},
    "video": {"agent_dir": "../idea-video-agent", "pick": "top", "workflow": "faceless-explainer", "destination": "shorts",
              "aspect": "1080x1920", "length": "30s", "language": "en", "angle": "auto",
              "voice": "elevenlabs", "voice_id": "", "music": "elevenlabs", "music_mood": "auto"},
}


def load() -> dict[str, dict]:
    data = {}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            data = tomllib.load(f)
    merged = {}
    for section, defaults in DEFAULTS.items():
        merged[section] = {**defaults, **data.get(section, {})}
    return merged


def section(name: str) -> dict:
    return load()[name]


def describe() -> str:
    cfg = load()
    lines = [f"{'pipeline.toml' if CONFIG_FILE.exists() else 'pipeline.toml (missing — using built-in defaults)'}", ""]
    for name, values in cfg.items():
        lines.append(f"[{name}]")
        for k, v in values.items():
            lines.append(f"  {k:<16} = {v!r}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
    sys.exit(0)
