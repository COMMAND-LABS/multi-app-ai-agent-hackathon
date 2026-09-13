# Project notes for Claude

- Python project managed with `uv`. Run things as `uv run python -m integrations.<name> ...`.
- Pipeline settings (channels, thresholds, repeatability rules) live in `pipeline.toml`; edit that for lasting changes, use CLI flags for one-off runs.
- Credentials live only in `.env` (see `.env.example`). Never print, log, or commit secret values. If a credential is missing, tell the user which variable to fill.
- Pulled data goes under `data/<platform>/<kind>/`; read `latest_*` files for current state.
- Skills are in `.claude/skills/`: `pipeline` (the 9-step flow, progress log, evaluation), `gcs`, `metricool`, `youtube`, `airtable`. Run `uv run pytest` after code changes and `uv run python -m analysis.evaluate` after pipeline runs.
- Progress for humans: `logs/progress.log` (one line per step/milestone from every actor). Detailed per-session tool logs are separate.
- Skills (old note): `pipeline` (the 5-step flow and how run_ids tie logs, reports, and Airtable together), `youtube`, `airtable`.
- MCP connectors for Airtable/Metricool exist in this environment and are fine for reading/verifying, but pipeline writes go through the CLI so they are logged, receipted, and evaluated.
- Every tool call is logged by a hook (`.claude/settings.json` -> `scripts/log_tool_call.py`). Each session gets its own `logs/<date>_<time>_<session>.log` (one readable line per call/result) plus a `.jsonl` with full payloads; `logs/latest.log` points at the current session. `logs/` is git-ignored, and the logger redacts .env values, secret-looking env vars, and key-shaped strings before writing. Still: never `cat .env` or echo a credential; print only whether it is set.
- Pipeline goal: (1) pull videos for channels in a niche, (2) find outlier multiples (video views / channel median), (3) search YouTube for other videos on the same topic using title+description, (4) score repeatability, (5) write repeatable ideas to an Airtable table, (6) hand the top idea as a brief to the separate video sub-agent project at ../idea-video-agent, which builds a 9:16 short with HyperFrames.
