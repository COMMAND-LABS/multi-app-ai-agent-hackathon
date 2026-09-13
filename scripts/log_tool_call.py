#!/usr/bin/env python3
"""Claude Code hook: log every tool call to a per-session, timestamped file.

Each session gets logs/<YYYY-MM-DD_HH-MM-SS>_<session8>.log (readable, one line per call/result)
and a matching .jsonl (full payloads). logs/latest.log always points at the current session's log.

Works for SessionStart (names the file), PreToolUse, PostToolUse, and PostToolUseFailure.
Never blocks: any error is swallowed so a logging failure can't interrupt the agent.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
SESSION_DIR = os.path.join(LOG_DIR, ".sessions")   # session_id -> log file stem

# The ONE shared progress log. The main project owns logs/progress.log; the video agent's launcher
# points PIPELINE_PROGRESS_LOG at that same file so both agents' milestones land in one place.
PROGRESS_LOG = os.environ.get("PIPELINE_PROGRESS_LOG") or os.path.join(ROOT, "logs", "progress.log")
ACTOR = os.environ.get("PIPELINE_ACTOR") or ("video-agent" if "video-agent" in ROOT else "main-agent")
def _run_id():
    if os.environ.get("PIPELINE_RUN_ID"):
        return os.environ["PIPELINE_RUN_ID"]
    latest = os.path.join(LOG_DIR, "latest.log")   # the main project's current session = the run id
    try:
        return os.path.splitext(os.path.basename(os.readlink(latest)))[0] if os.path.islink(latest) else "-"
    except OSError:
        return "-"


RUN_ID = _run_id()
# (regex on the Bash command, label) — only these become progress lines; everything else stays in the session log
MILESTONES = [
    (re.compile(r"hyperframes init"), "init HyperFrames project"),
    (re.compile(r"hyperframes skills update (\S+)"), "install workflow {1}"),
    (re.compile(r"audio\.mjs (generate|sync-durations|fetch-sfx)"), "audio: {1}"),
    (re.compile(r"elevenlabs_music"), "music: ElevenLabs bed"),
    (re.compile(r"hyperframes (lint|check|snapshot)"), "verify: {1}"),
    (re.compile(r"hyperframes render"), "render"),
    (re.compile(r"cp .*video\.mp4"), "deliver video.mp4"),
]


def progress(step, message):
    try:
        os.makedirs(os.path.dirname(PROGRESS_LOG), exist_ok=True)
        with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
            f.write(redact(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {RUN_ID:<28}  {ACTOR:<11}  {step:<13}  {message}") + "\n")
    except OSError:
        pass


def milestone_for(event, tool, args):
    if event == "SessionStart":
        return ("session", "started")
    if event == "Stop":
        return ("session", "finished (agent stopped)")
    if event != "PreToolUse":
        return None
    if tool == "Skill":
        return ("skill", f"/{args.get('skill', '')} {args.get('args', '')}".strip())
    if tool == "Agent":
        return ("subagent", short(args.get("description", ""), 90))
    if tool == "Bash" and ACTOR == "video-agent":   # main-agent steps log themselves; only the video agent's shell work is a milestone
        cmd = args.get("command", "")
        for rx, label in MILESTONES:
            m = rx.search(cmd)
            if m:
                text = label
                for i in range(1, (m.re.groups or 0) + 1):
                    text = text.replace("{%d}" % i, (m.group(i) or "").strip())
                return ("step", text)
    return None
MAX_ARG = 300      # chars per argument value in the readable log
MAX_LINE = 1200    # chars per readable line

# ------------------------------------------------------------------ redaction
# Nothing from .env, no secret-looking environment variable, and no key-shaped string may
# reach the log files. Redaction happens on the final text, so it covers tool arguments,
# tool output, and anything a command happened to print.
_SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PAT|API)", re.I)
_BENIGN_KEY_RE = re.compile(r"(_FILE|_DIR|_PATH|_URL|_HOST|_HANDLE|_NAME)$", re.I)
_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),                     # Google API key
    re.compile(r"pat[A-Za-z0-9]{14}\.[a-f0-9]{64}"),           # Airtable PAT
    re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),                   # Google OAuth access token
    re.compile(r"1//[0-9A-Za-z_-]{20,}"),                      # Google OAuth refresh token
    re.compile(r"GOCSPX-[0-9A-Za-z_-]{10,}"),                  # Google OAuth client secret
    re.compile(r"\b(sk|rk)-[A-Za-z0-9_-]{20,}"),               # OpenAI/Stripe-style keys
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),   # GitHub tokens
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),               # Slack tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{20,}"),       # Authorization headers
    # NAME=value / "name": "value" where NAME ends in key/token/secret/password (any prefix, e.g. METRICOOL_USER_TOKEN)
    re.compile(r"(?i)[A-Za-z0-9_-]*(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret|password|passwd|token|key)\s*[\\\"']*\s*[=:]\s*[\\\"']*([A-Za-z0-9._~+/=-]{8,})"),
]


def _env_file_values():
    out = {}
    for path in (os.path.join(ROOT, ".env"), *glob.glob(os.path.join(ROOT, ".env.*"))):
        if path.endswith(".example") or not os.path.isfile(path):
            continue
        try:
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\"'")
                if not v or _BENIGN_KEY_RE.search(k):
                    continue
                if len(v) >= 8 or _SECRET_KEY_RE.search(k):
                    out[v] = k
        except OSError:
            pass
    return out


def _process_env_values():
    out = {}
    for k, v in os.environ.items():
        if v and len(v) >= 8 and _SECRET_KEY_RE.search(k) and not _BENIGN_KEY_RE.search(k):
            out[v] = k
    return out


def _token_file_values():
    out = {}
    for path in glob.glob(os.path.join(ROOT, ".secrets", "*.json")):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k, v in (data.items() if isinstance(data, dict) else []):
            if isinstance(v, str) and len(v) >= 8 and _SECRET_KEY_RE.search(k):
                out[v] = f"{os.path.basename(path)}:{k}"
    return out


def _secret_values():
    vals = {}
    vals.update(_token_file_values())
    vals.update(_process_env_values())
    vals.update(_env_file_values())
    # longest first so a value that contains another is replaced whole
    return sorted(vals.items(), key=lambda kv: -len(kv[0]))


_SECRETS = None


def redact(text: str) -> str:
    global _SECRETS
    if _SECRETS is None:
        _SECRETS = _secret_values()
    for value, name in _SECRETS:
        if value in text:
            text = text.replace(value, f"[REDACTED:{name}]")
    for pat in _PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: m.group(0).replace(m.group(2), "[REDACTED]"), text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def short(value, limit=MAX_ARG):
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "⏎ ")
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} chars)"


def describe_args(tool, args):
    """Pick the arguments a human cares about for the common tools."""
    if not isinstance(args, dict):
        return short(args)
    if tool == "Bash":
        return f"$ {short(args.get('command', ''), 600)}"
    if tool in ("Read", "Write", "Edit", "NotebookEdit"):
        extra = ""
        if tool == "Edit":
            extra = f"  old={short(args.get('old_string', ''), 80)!r} -> new={short(args.get('new_string', ''), 80)!r}"
        if tool == "Write":
            extra = f"  ({len(args.get('content', ''))} chars)"
        return f"{args.get('file_path', '')}{extra}"
    if tool in ("Grep", "Glob"):
        return " ".join(f"{k}={short(v, 120)}" for k, v in args.items())
    if tool == "Skill":
        return f"/{args.get('skill', '')} {args.get('args', '')}".strip()
    if tool == "Agent":
        return f"[{args.get('subagent_type', 'general')}] {short(args.get('description', ''), 120)}: {short(args.get('prompt', ''), 200)}"
    # MCP tools and everything else: show every argument, truncated.
    return " ".join(f"{k}={short(v)}" for k, v in args.items())


def describe_result(payload):
    resp = payload.get("tool_response")
    if resp is None:
        err = payload.get("error") or payload.get("tool_error")
        return f"FAILED {short(err, 300)}" if err else "done"
    if isinstance(resp, dict):
        if resp.get("error") or resp.get("is_error"):
            return f"FAILED {short(resp.get('error') or resp, 300)}"
        # Common shapes: {"stdout":..}, {"content":[..]}, {"filePath":..}, {"success":..}
        for key in ("stdout", "output", "filePath", "content", "result"):
            if key in resp:
                return f"ok {key}={short(resp[key], 200)}"
        return f"ok {short(resp, 200)}"
    return f"ok {short(resp, 200)}"


def session_stem(session_id, now):
    """Return the log-file stem for this session, creating it on first sight."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    marker = os.path.join(SESSION_DIR, session_id or "unknown")
    if os.path.exists(marker):
        return open(marker, encoding="utf-8").read().strip()
    stem = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{(session_id or 'unknown')[:8]}"
    with open(marker, "w", encoding="utf-8") as f:
        f.write(stem)
    return stem


def point_latest(stem):
    for ext in ("log", "jsonl"):
        link = os.path.join(LOG_DIR, f"latest.{ext}")
        target = f"{stem}.{ext}"
        try:
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
            os.symlink(target, link)
        except OSError:
            pass


def main():
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    event = payload.get("hook_event_name", "ToolEvent")
    tool = payload.get("tool_name", "?")
    args = payload.get("tool_input", {})
    now = datetime.now(timezone.utc).astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    session_id = payload.get("session_id") or ""
    session = session_id[:8]

    ms = milestone_for(event, tool, args)
    if ms:
        progress(*ms)
    if event == "Stop":
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    stem = session_stem(session_id, now)
    text_log = os.path.join(LOG_DIR, f"{stem}.log")
    json_log = os.path.join(LOG_DIR, f"{stem}.jsonl")

    if event == "SessionStart":
        cwd = payload.get("cwd", ROOT)
        line = f"{stamp}  SESSION start ({payload.get('source', 'startup')}) in {cwd}"
        point_latest(stem)
        with open(text_log, "a", encoding="utf-8") as f:
            f.write(redact(line) + "\n")
        with open(json_log, "a", encoding="utf-8") as f:
            f.write(redact(json.dumps({"ts": now.isoformat(), **payload}, ensure_ascii=False)) + "\n")
        return
    if not os.path.exists(text_log):
        point_latest(stem)   # first tool call of a session that had no SessionStart hook

    if event == "PreToolUse":
        line = f"{stamp}  CALL   {tool:<40} {describe_args(tool, args)}"
    elif event == "PostToolUseFailure":
        line = f"{stamp}  ERROR  {tool:<40} {describe_result(payload)}"
    else:
        line = f"{stamp}  RESULT {tool:<40} {describe_result(payload)}"
    if session:
        line += f"   [session {session}]"
    line = line if len(line) <= MAX_LINE else line[:MAX_LINE] + "…"

    with open(text_log, "a", encoding="utf-8") as f:
        f.write(redact(line) + "\n")
    with open(json_log, "a", encoding="utf-8") as f:
        f.write(redact(json.dumps({"ts": now.isoformat(), **payload}, ensure_ascii=False)) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the agent because of logging
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(os.path.join(LOG_DIR, "logger-errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  LOGGER-ERROR {exc}\n")
        except Exception:
            pass
    sys.exit(0)
