---
name: metricool
description: Put a finished video on the Metricool content calendar as a draft or scheduled post (step 7), or inspect the calendar. Use for "schedule / post / add to the calendar" requests.
---

# Metricool content calendar

```bash
uv run python -m integrations.metricool.schedule [--run-id X] [--brief-id ID] [--networks instagram tiktok] [--when 2026-09-15T10:00:00] [--draft|--no-draft] [--dry-run]
```

- Credentials in `.env`: `METRICOOL_USER_TOKEN` (Settings → API, Advanced plan), `METRICOOL_USER_ID`,
  `METRICOOL_BLOG_ID` (the brand). If the token is missing, say so; never ask for it in chat.
- Reads the GCS URL from `reports/<run_id>/deliverables.json` (run step 6 first) and the idea title
  from `repeatability.csv`; builds the payload exactly as the Metricool scheduler expects
  (`providers`, `media`, `publicationDate{dateTime,timezone}`, per-network `*Data`).
- Defaults from `pipeline.toml` `[metricool]`: Instagram Reel, draft = true (a human approves in
  Metricool), tomorrow 10:00 brand-local, AI-generated flags on, private/self-only for YouTube/TikTok.
- Receipt: `reports/<run_id>/metricool_schedule.md` (includes the payload); post id stored in
  `deliverables.json`. `--dry-run` builds and records the payload without calling the API.
- A Metricool MCP connector may exist in the session (`getBrandSettings`, `getScheduledPosts`): fine
  for reading the brand/timezone/networks or verifying a post landed; keep the write on the CLI so it
  is logged and receipted.
