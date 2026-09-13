---
name: pipeline
description: Run the full YouTube idea pipeline (pull -> outliers -> repeatability -> Airtable -> brief -> video -> GCS -> Metricool -> evaluate) or any single step, and trace a run by its run_id across logs/, reports/, and Airtable. Use when the user says "run the analysis", "find outliers", "check repeatability", "push to Airtable", or asks what happened in a run.
---

# Idea pipeline

Nine steps, one command each (or `uv run python -m analysis.pipeline` for all of them in order). Every artifact from one session shares a **run_id** equal to the
tool-call log stem, so a run can be traced from the log to the reports to the Airtable rows.

```
logs/<run_id>.log                       every tool call (hook)          ┐
reports/<run_id>/outliers.md + .csv     step 2 output                    │ same run_id
reports/<run_id>/repeatability.md/.csv  step 3 output (+ _matches.csv)   │
reports/<run_id>/airtable_sync.md       step 4 receipt with record IDs   │
reports/<run_id>/handoff.md             step 5 receipt (which brief went where) │
reports/<run_id>/gcs_upload.md          step 6 receipt                    │
reports/<run_id>/metricool_schedule.md  step 7 receipt (+ payload)        │
reports/<run_id>/deliverables.json      per brief: video path, GCS URL, Metricool post id │
reports/<run_id>/evaluation.md          step 8: PASS/WARN/FAIL for everything above ┘
logs/progress.log                       THE progress log: every step + both agents' milestones
Airtable "Repeatable Ideas" table       one row per idea, "Run ID" column
../idea-video-agent/briefs/<run_id>__<video_id>.md   the brief the video sub-agent receives
../idea-video-agent/output/<run_id>__<video_id>/     video.mp4 + SUMMARY.md (carries run_id)
```

## Steps

| # | Command | Cost | Output |
|---|---|---|---|
| 1 | `uv run python -m integrations.youtube pull-all` (channels + days from pipeline.toml) | ~2 quota units / 50 videos per channel | `data/youtube/<handle>/videos/latest_since_<date>.csv` |
| 2 | `uv run python -m analysis.outliers --window since_<date>` | none (local) | `reports/<run_id>/outliers.{md,csv}` |
| 3 | `uv run python -m analysis.repeatability` | **~100 units per outlier** | `reports/<run_id>/repeatability.{md,csv}`, `repeatability_matches.csv` |
| 4 | `uv run python -m integrations.airtable.push [--dry-run]` | Airtable API | `reports/<run_id>/airtable_sync.md` + Airtable rows |
| 5 | `uv run python -m analysis.handoff [--idea ID \| --top N] [--launch]` | none (brief) / a full HyperFrames build if `--launch` | brief in the video agent's `briefs/`, `reports/<run_id>/handoff.md` |
| 6 | `uv run python -m integrations.gcs.upload [--dry-run]` | GCS API | video in `gs://<bucket>/videos/<run_id>/`, `deliverables.json`, `gcs_upload.md` |
| 7 | `uv run python -m integrations.metricool.schedule [--dry-run]` | Metricool API | draft/scheduled post, `metricool_schedule.md` |
| 8 | `uv run python -m analysis.evaluate` | none | `evaluation.md` — exit 1 on any FAIL |
| all | `uv run python -m analysis.pipeline [--from A --to B] [--skip video] [--dry-run]` | sum of the above | stops at the first failing step |

## Step 5: the video sub-agent

The video sub-agent is a **separate Claude Code project** at `[video] agent_dir` in pipeline.toml
(default `../idea-video-agent`, a sibling so it does not inherit this project's CLAUDE.md). It gets
its context only from the brief: idea, evidence, scrubbed description (no links/emails/promos), and a
fully answered video spec. `handoff` writes the brief and a receipt; `--launch` (or
`scripts/run_video_agent.sh <brief>`) runs `claude -p` headlessly in that folder with fresh context.
The agent follows its own CLAUDE.md + `short-from-brief` skill, which routes through `/hyperframes`
→ the `[video] workflow` (`motion-graphics`, default: ~10s unnarrated kinetic type, a few minutes; or `faceless-explainer`: narrated 30-90s, much slower), renders a 9:16 short, and writes `output/<brief-id>/video.mp4` + SUMMARY.md.
Voice and music come from `[video] voice` / `music` (`elevenlabs`, `default`, or `none`) and land in the
brief's `## Customizations`. ElevenLabs needs `ELEVENLABS_API_KEY` in the **agent's** `.env` (not this
project's); the launcher exports it into the headless session and the agent's logger redacts it. Voice
goes through the media-use audio engine's native ElevenLabs route; music uses the agent's
`scripts/elevenlabs_music.sh` (ElevenLabs Music API) because the engine has no ElevenLabs music route.
If a headless run dies mid-build (usage limit, crash), do not restart from scratch: the project under
the agent's `videos/<name>/` keeps everything done so far. Relaunch with a resume note as the 3rd
argument: `scripts/run_video_agent.sh <brief> "" "Resume videos/<name>: audio and frames exist, do not re-init; continue from step N"`.
`scripts/video_agent_status.sh` shows the stage reached. A run that ends with "session limit" in its
output file is the usage limit, not a bug.
The agent folder must be trusted once (open Claude Code there interactively) or its permission
allowlist is ignored in headless mode. Even a 10s piece takes a few minutes (skill install, init, build, checks, headless-browser render); tell the user before launching. If the workspace is untrusted the launcher passes the allowlist as session flags.

## Progress log and evaluation

- `logs/progress.log` is the single place to see what happened: every step writes a line
  (`time  run_id  actor  step  message`), the main agent's skill calls land there, and the video
  sub-agent's milestones (init, audio, music, frame workers, checks, render, deliver, stop) are
  written into the same file by its hook via `PIPELINE_PROGRESS_LOG`. Show it with
  `uv run python -m analysis.progress [-n 40] [--run-id X] [-f]`.
- `analysis.evaluate` is the reliability gate: it re-derives what should exist for a run and checks
  the artifacts agree (thresholds respected, evidence excludes the idea's own channel, Airtable rows
  = repeatable ideas, brief has no links/emails, video duration/aspect/audio match the brief's spec,
  GCS URL answers HEAD with the uploaded size, Metricool post id recorded, progress lines present).
  Run it after any step; quote its PASS/WARN/FAIL counts in your summary.
- `uv run pytest` runs the offline test suite (flatteners, outlier math, similarity, brief scrubbing,
  Airtable/Metricool payloads, logger redaction, progress milestones). Run it after code changes.

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
