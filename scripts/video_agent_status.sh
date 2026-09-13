#!/usr/bin/env bash
# Plain-English status of the video sub-agent.   scripts/video_agent_status.sh [-f]   (-f = refresh every 10s)
AGENT_DIR="$(cd "$(dirname "$0")/.." && uv run python -c 'from analysis import config; print(config.section("video")["agent_dir"])')"
AGENT_DIR="$(cd "$(dirname "$0")/.." && cd "$AGENT_DIR" && pwd)"
show() {
  LOG=$(ls -t "$AGENT_DIR"/logs/2026-*.log 2>/dev/null | head -1)
  PROJ=$(ls -td "$AGENT_DIR"/videos/*/ 2>/dev/null | head -1)
  echo "VIDEO SUB-AGENT  ·  $(date '+%H:%M:%S')"
  if pgrep -f "claude -p New brief" >/dev/null; then echo "  status     : RUNNING"; else echo "  status     : not running"; fi
  [ -n "$LOG" ] && echo "  session    : $(basename "$LOG" .log)  ·  $(grep -c 'CALL' "$LOG") tool calls  ·  last action $(tail -1 "$LOG" | cut -c12-19)"
  if [ -n "$PROJ" ]; then
    P="${PROJ%/}"; echo "  project    : videos/$(basename "$P")"
    stage="0 setup"
    [ -f "$P/BRIEF.md" ]            && stage="1 brief written"
    [ -f "$P/frame.md" ]            && stage="2 design system chosen"
    [ -f "$P/SCRIPT.md" ] || [ -f "$P/STORYBOARD.md" ] && stage="3 script + storyboard written"
    [ -f "$P/audio_meta.json" ]     && stage="4 voiceover generated"
    ls "$P"/assets/bgm/* >/dev/null 2>&1 && stage="4b music bed generated"
    n=$(ls "$P"/compositions/frames/*.html 2>/dev/null | wc -l | tr -d ' '); [ "$n" -gt 0 ] && stage="5 building frames ($n done)"
    [ -f "$P/renders/video.mp4" ]   && stage="6 RENDERED (renders/video.mp4)"
    echo "  stage      : $stage"
  fi
  OUT=$(ls -td "$AGENT_DIR"/output/*/ 2>/dev/null | head -1)
  [ -n "$OUT" ] && [ -f "$OUT/video.mp4" ] && echo "  last done  : output/$(basename "$OUT")/video.mp4"
  echo "  last 3     :"; [ -n "$LOG" ] && tail -3 "$LOG" | cut -c12-19,28-34,68-140 | sed 's/^/     /'
  echo "  live log   : tail -f $AGENT_DIR/logs/latest.log"
}
if [ "${1:-}" = "-f" ]; then while true; do clear; show; sleep 10; done; else show; fi
