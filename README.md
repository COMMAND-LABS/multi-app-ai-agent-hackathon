# multi-app-ai-agent

Claude Code acts as the agent driving five integrations: **YouTube**, **Airtable**, **Google Cloud Storage**, **Metricool**, and a **HyperFrames video sub-agent**. Each integration is a small Python client plus a CLI, a Claude skill under `.claude/skills/`, and pulled data lands in `data/`.

## Setup

```bash
cp .env.example .env      # then fill in credentials
uv sync                   # installs deps into .venv
uv run python -m integrations.youtube check
```

## YouTube

Needs a YouTube Data API v3 key (`YOUTUBE_API_KEY`). For your own channel's private analytics, also set `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` (OAuth "Desktop app" client, with YouTube Analytics API enabled) and run:

```bash
uv run python -m integrations.youtube auth
```

Examples:

```bash
uv run python -m integrations.youtube channel @mkbhd
uv run python -m integrations.youtube videos @mkbhd --max 100
uv run python -m integrations.youtube comments dQw4w9WgXcQ --max 200
uv run python -m integrations.youtube search "ai agents" --max 25 --order viewCount
uv run python -m integrations.youtube analytics --days 28 --dimensions day     # OAuth
```

Full command reference: [.claude/skills/youtube/SKILL.md](.claude/skills/youtube/SKILL.md).

## Layout

```
.env.example           credential template (copy to .env) — secrets only
pipeline.toml          pipeline settings: channels, thresholds, rules — no secrets
integrations/
  config.py            loads .env into typed settings
  youtube/             client.py (API), auth.py (OAuth), storage.py (data/ writer), cli.py
data/youtube/<handle>/ pulled JSON + CSV per channel, git-ignored
.claude/skills/        skills the agent uses to operate each integration
.secrets/              cached OAuth tokens, git-ignored
```

## The pipeline

Find proven video ideas in a niche and hand them to Airtable for content generation. Every artifact from one session shares a `run_id` (the tool-call log's stem), so a run can be traced end to end.

```bash
# 0. settings (channels, thresholds, rules) live in pipeline.toml — no secrets there
uv run python -m analysis.config
# 1. pull videos for every channel in pipeline.toml (YouTube Data API)
uv run python -m integrations.youtube pull-all
# 2. outlier multiples: views / channel median      -> reports/<run_id>/outliers.md
uv run python -m analysis.outliers --window since_2026-06-15
# 3. repeatability: other channels on the same topic -> reports/<run_id>/repeatability.md
uv run python -m analysis.repeatability
# 4. push repeatable ideas to Airtable                -> reports/<run_id>/airtable_sync.md
uv run python -m integrations.airtable.push --dry-run   # then without --dry-run
# 5. hand the top idea to the video sub-agent          -> ../idea-video-agent/briefs/<run_id>__<id>.md
uv run python -m analysis.handoff --launch   # --launch builds the short headlessly (minutes)
# 6. upload the video to Google Cloud Storage           -> deliverables.json (public URL)
uv run python -m integrations.gcs.upload
# 7. put it on the Metricool content calendar (draft)   -> metricool_schedule.md
uv run python -m integrations.metricool.schedule
# 8. evaluate the whole run                             -> evaluation.md (PASS/WARN/FAIL)
uv run python -m analysis.evaluate

# or all of it in one go (stops at the first failing step):
uv run python -m analysis.pipeline [--skip video] [--dry-run]
```

The orchestrator judges the video step by its deliverable, not the sub-agent's exit code: if the headless session ends without `video.mp4`, it relaunches the agent with a resume note, up to three times, then continues.

## One progress log

Everything that happens, from every step and both agents, lands in **`logs/progress.log`** as one line each:

```
2026-09-13 15:31:02  2026-09-13_13-40-22_a9aa5ed2  pipeline     repeatability  10 repeatable of 16 checked (~1712 quota units) → reports/…/repeatability.md
2026-09-13 15:36:58  2026-09-13_13-40-22_a9aa5ed2  video-agent  step           init HyperFrames project
```

```bash
uv run python -m analysis.progress -f        # follow it live
uv run python -m analysis.progress --run-id 2026-09-13_13-40-22_a9aa5ed2
```

## Reliability and evaluation

- `uv run python -m analysis.evaluate` checks every artifact of a run against what the pipeline promised and writes `reports/<run_id>/evaluation.md` with a PASS/WARN/FAIL table. It exits non-zero on any FAIL, so it works as a gate in the orchestrator.
- `uv run pytest` runs the offline unit tests (outlier math, topic similarity, brief scrubbing, Airtable and Metricool payload shapes, secret redaction in the logs).
- Every external write has a `--dry-run` that produces the same receipt without touching the service.
- Re-running any step is safe: Airtable upserts, GCS overwrites the same object, Metricool records the post id so you can see duplicates before they happen.

## The video sub-agent

Step 5 hands one idea to **[idea-video-agent](../idea-video-agent/)**, a separate Claude Code project
in a sibling folder. Separate on purpose: it starts with fresh context, its own `CLAUDE.md`, skill,
hooks, and permissions, and the only thing it receives is the brief file. It turns the brief into a
9:16 short with HyperFrames (`/hyperframes` → `motion-graphics` for a 10s kinetic piece, or `faceless-explainer` for a narrated 30-90s explainer; set in `pipeline.toml` [video]) and writes
`output/<brief-id>/video.mp4` plus a `SUMMARY.md` that carries the `run_id`, so the video traces back
to the report, the Airtable row, and the log that produced it.

Voice and music are optional (`[video] voice` / `music` in `pipeline.toml`). With `elevenlabs`, the agent's own `.env` must hold `ELEVENLABS_API_KEY`; voice uses the media engine's ElevenLabs route and music is generated with the agent's `scripts/elevenlabs_music.sh`.

Launch it headlessly with `scripts/run_video_agent.sh <brief-file>`, or open Claude Code in that
folder and say "New brief: briefs/<file>.md". Trust the folder once (interactive session) before the
first headless run, or its permission allowlist is ignored.

Change a rule by editing [pipeline.toml](pipeline.toml); override it for one run with the matching flag (e.g. `--threshold 4`). Full details in [.claude/skills/pipeline/SKILL.md](.claude/skills/pipeline/SKILL.md).

## Tool-call logs (per session, detailed)

A Claude Code hook logs every tool call the agent makes. Each session (run) gets its own timestamped file, e.g. `logs/2026-09-13_13-40-22_a9aa5ed2.log`. Follow the current session with:

```bash
tail -f logs/latest.log
```

Each `CALL` line shows the tool and its arguments; each `RESULT` line shows a short outcome; `SESSION start` marks the beginning of a run. The full untruncated payloads are in the matching `.jsonl` file next to it.

The logger redacts secrets before writing: every value from `.env`, any environment variable whose name looks secret (KEY, TOKEN, SECRET, PASSWORD...), cached OAuth tokens under `.secrets/`, and key-shaped strings (Google, Airtable, GitHub, Slack, Bearer headers, `NAME=value` pairs). They appear as `[REDACTED:NAME]`. `logs/` is git-ignored regardless.

## License

MIT. See [LICENSE](LICENSE).

To see what the video sub-agent is doing right now, in plain words:

```bash
scripts/video_agent_status.sh        # one snapshot: running?, stage, last actions
scripts/video_agent_status.sh -f     # refresh every 10 seconds
tail -f ../idea-video-agent/logs/latest.log   # every tool call, live
```
