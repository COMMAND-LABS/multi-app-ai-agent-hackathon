import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_logger(tmp: Path, payload: dict, env: dict):
    (tmp / "scripts").mkdir(exist_ok=True)
    (tmp / "scripts" / "log_tool_call.py").write_text((ROOT / "scripts" / "log_tool_call.py").read_text())
    subprocess.run([sys.executable, str(tmp / "scripts" / "log_tool_call.py")], input=json.dumps(payload), text=True, env={**os.environ, **env}, check=True)
    return "".join(p.read_text() for p in (tmp / "logs").rglob("*") if p.is_file()) if (tmp / "logs").exists() else ""


def test_env_and_pattern_secrets_never_reach_logs(tmp_path):
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=AIzaSyTESTKEY1234567890abcdefghijklmn\nDATA_DIR=data\n")
    out = run_logger(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "cat .env"},
                                "tool_response": {"stdout": "YOUTUBE_API_KEY=AIzaSyTESTKEY1234567890abcdefghijklmn\nMETRICOOL_USER_TOKEN=abcdef1234567890ZZ"}},
                     {"MY_TEST_API_KEY": "SHELLSECRETVALUE12345", "PIPELINE_PROGRESS_LOG": str(tmp_path / "logs" / "progress.log")})
    assert "AIzaSyTESTKEY" not in out and "abcdef1234567890ZZ" not in out and "[REDACTED:YOUTUBE_API_KEY]" in out


def test_progress_milestones_only_for_meaningful_commands(tmp_path):
    env = {"PIPELINE_PROGRESS_LOG": str(tmp_path / "logs" / "progress.log"), "PIPELINE_RUN_ID": "run_t", "PIPELINE_ACTOR": "video-agent"}
    run_logger(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": {"command": "ls -la"}}, env)
    run_logger(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": {"command": "npx hyperframes render . -o out.mp4"}}, env)
    prog = (tmp_path / "logs" / "progress.log").read_text()
    assert prog.count("\n") == 1 and "render" in prog and "run_t" in prog and "video-agent" in prog
