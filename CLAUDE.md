# Project notes for Claude

- Python project managed with `uv`. Run things as `uv run python -m integrations.<name> ...`.
- Pipeline settings (channels, thresholds, repeatability rules) live in `pipeline.toml`; edit that for lasting changes, use CLI flags for one-off runs.
- Credentials live only in `.env` (see `.env.example`). Never print, log, or commit secret values. If a credential is missing, tell the user which variable to fill.
- Pulled data goes under `data/<platform>/<kind>/`; read `latest_*` files for current state.
- Skills are in `.claude/skills/`: `pipeline` (the 4-step flow and how run_ids tie logs, reports, and Airtable together), `youtube`, `airtable`.
- Metricool integration is planned next. MCP connectors for Airtable/Metricool exist in this environment, but pipeline writes go through the CLI so they are logged and produce sync reports.
- Every tool call is logged by a hook (`.claude/settings.json` -> `scripts/log_tool_call.py`). Each session gets its own `logs/<date>_<time>_<session>.log` (one readable line per call/result) plus a `.jsonl` with full payloads; `logs/latest.log` points at the current session. `logs/` is git-ignored, and the logger redacts .env values, secret-looking env vars, and key-shaped strings before writing. Still: never `cat .env` or echo a credential; print only whether it is set.
- Pipeline goal: (1) pull videos for channels in a niche, (2) find outlier multiples (video views / channel median), (3) search YouTube for other videos on the same topic using title+description, (4) score repeatability, (5) write repeatable ideas to an Airtable table for downstream social content generation.
