#!/usr/bin/env bash
# Run the video sub-agent headlessly on one brief.
#   scripts/run_video_agent.sh <brief-file-name> [agent_dir] [resume-note]
# A resume note (3rd arg) tells the agent the project already exists and where to pick up.
# The sub-agent is a separate Claude Code project: it starts with fresh context, its own CLAUDE.md,
# skills, hooks, and permissions, and is told only which brief to read.
set -euo pipefail
BRIEF="${1:?usage: run_video_agent.sh <brief-file-name> [agent_dir] [resume-note]}"
RESUME_NOTE="${3:-}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="${2:-$(cd "$HERE" && uv run python -c 'from analysis import config; print(config.section("video")["agent_dir"])')}"
AGENT_DIR="$(cd "$HERE" && cd "$AGENT_DIR" && pwd)"
[ -f "$AGENT_DIR/briefs/$BRIEF" ] || { echo "brief not found: $AGENT_DIR/briefs/$BRIEF" >&2; exit 1; }
cd "$AGENT_DIR"
echo "video agent: $AGENT_DIR  brief: $BRIEF" >&2
# Export the agent's own secrets (e.g. ELEVENLABS_API_KEY) so its audio tools can use them. Never echoed;
# the agent's tool-call logger redacts *_API_KEY values.
if [ -f "$AGENT_DIR/.env" ]; then set -a; . "$AGENT_DIR/.env"; set +a; fi
# ElevenLabs caps concurrent requests per plan; the media engine defaults to 4 parallel TTS calls and drops lines that get rejected.
export HYPERFRAMES_TTS_CONCURRENCY="${HYPERFRAMES_TTS_CONCURRENCY:-1}"
# One shared progress log for both agents (logs/progress.log in the main project) + the run id from the brief name.
export PIPELINE_PROGRESS_LOG="$HERE/logs/progress.log" PIPELINE_ACTOR="video-agent" PIPELINE_RUN_ID="${BRIEF%%__*}"
if ! python3 -c "import json,sys; d=json.load(open('$HOME/.claude.json')); sys.exit(0 if d.get('projects',{}).get('$AGENT_DIR',{}).get('hasTrustDialogAccepted') else 1)" 2>/dev/null; then
  echo "WARNING: $AGENT_DIR is not a trusted workspace yet, so its permission allowlist is ignored and render commands will be denied." >&2
  echo "         Open Claude Code in that folder once and accept the trust dialog, then re-run." >&2
fi
# Session-scoped allowlist (mirrors the agent's .claude/settings.json) so headless runs work even
# before the workspace has been trusted interactively.
ALLOW="Read,Write,Edit,Glob,Grep,Skill,Agent,Bash(npx hyperframes *),Bash(npx hyperframes@latest *),Bash(npx skills *),Bash(node *),Bash(npm *),Bash(npx *),Bash(ffmpeg *),Bash(ffprobe *),Bash(ls *),Bash(cat *),Bash(head *),Bash(tail *),Bash(wc *),Bash(find *),Bash(grep *),Bash(mkdir *),Bash(cp *),Bash(mv *),Bash(pwd),Bash(cd *),Bash(python3 *),Bash(true)"
PROMPT="New brief: briefs/$BRIEF. Follow CLAUDE.md and the short-from-brief skill. You are headless: never ask a question, take the recommended option at every gate, render, and deliver output/${BRIEF%.md}/video.mp4 with SUMMARY.md."
[ -n "$RESUME_NOTE" ] && PROMPT="$PROMPT RESUME: $RESUME_NOTE"
exec env -u CLAUDECODE claude -p "$PROMPT" \
  --permission-mode acceptEdits --allowedTools "$ALLOW" --output-format text
