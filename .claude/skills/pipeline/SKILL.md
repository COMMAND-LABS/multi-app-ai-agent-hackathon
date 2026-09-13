---
name: pipeline
description: Run the full YouTube idea pipeline (pull channels -> outlier multiples -> repeatability -> Airtable) or any single step, and trace a run by its run_id across logs/, reports/, and Airtable. Use when the user says "run the analysis", "find outliers", "check repeatability", "push to Airtable", or asks what happened in a run.
---

# Idea pipeline

Four commands, run in order. Every artifact from one session shares a **run_id** equal to the
tool-call log stem, so a run can be traced from the log to the reports to the Airtable rows.

```
logs/<run_id>.log                       every tool call (hook)          ┐
reports/<run_id>/outliers.md + .csv     step 2 output                    │ same run_id
reports/<run_id>/repeatability.md/.csv  step 3 output (+ _matches.csv)   │
reports/<run_id>/airtable_sync.md       step 4 receipt with record IDs   ┘
Airtable "Repeatable Ideas" table       one row per idea, "Run ID" column
```

## Steps

| # | Command | Cost | Output |
|---|---|---|---|
| 1 | `uv run python -m integrations.youtube pull-all` (channels + days from pipeline.toml) | ~2 quota units / 50 videos per channel | `data/youtube/<handle>/videos/latest_since_<date>.csv` |
| 2 | `uv run python -m analysis.outliers --window since_<date>` | none (local) | `reports/<run_id>/outliers.{md,csv}` |
| 3 | `uv run python -m analysis.repeatability` | **~100 units per outlier** | `reports/<run_id>/repeatability.{md,csv}`, `repeatability_matches.csv` |
| 4 | `uv run python -m integrations.airtable.push [--dry-run]` | Airtable API | `reports/<run_id>/airtable_sync.md` + Airtable rows |

## Configuration

All knobs live in **`pipeline.toml`** at the project root (channels, pull window, outlier threshold,
repeatability rules, Airtable table). Secrets stay in `.env`. Print the effective values with
`uv run python -m analysis.config`. Any flag on a step overrides the file for that run only, and
every report header records the values actually used. When the user asks to change a rule
"from now on", edit `pipeline.toml`; when they ask for a one-off, pass the flag.

## Working guidance

- Run steps 2-4 in the **same session** as each other so they share a run_id, or pass `--run-id` explicitly.
  `analysis.run.current_run_id()` reads `logs/latest.log`; set `RUN_ID=...` to override.
- Before step 3, tell the user the quota cost (100 × number of outliers). Use `--limit N` to check only the top N.
- Always run step 4 with `--dry-run` first when the table or credentials are new; then run it live.
- Step 4 upserts on Run ID + Source Video ID, so re-running is safe.
- When asked "what happened in run X": read `reports/X/*.md` in order, then `logs/X.log` for the exact calls.
- Summaries for the user: lead with counts (outliers found, repeatable, pushed) and the report paths.
