"""Step 5: hand one repeatable idea to the video sub-agent as a self-contained brief.

    uv run python -m analysis.handoff [--run-id X] [--idea VIDEO_ID | --top N] [--launch]

Reads  reports/<run_id>/repeatability.csv (+ _matches.csv for the evidence lines)
Writes <agent_dir>/briefs/<run_id>__<video_id>.md   — the ONLY thing the sub-agent receives
       reports/<run_id>/handoff.md                    — receipt in this project
--launch runs scripts/run_video_agent.sh for each brief (headless Claude Code in the agent project).
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analysis import config as pipeline_config
from analysis.run import current_run_id, rel, report_dir
from integrations.config import PROJECT_ROOT


def pick_angle(title: str) -> str:
    t = title.lower()
    if re.match(r"^\d+\b", t) or re.search(r"\b(\d+ (ways|steps|things|tips|tools|prompts|channels|repos)|every|list)\b", t):
        return "listicle"
    if re.search(r"\bhow (to|i|i'd|we)\b", t):
        return "how-to"
    if re.search(r"\b(why|vs\.?|versus|explained|secret|truth)\b", t):
        return "concept"
    return "narrative" if re.search(r"\b(i tested|i tried|i built|i made|my)\b", t) else "concept"


_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PROMO_RE = re.compile(r"\b(code|coupon|discount|sponsor|affiliate|subscribe|follow me|join|sign ?up|free (month|trial|group))\b", re.I)


def clean_description(desc: str, max_chars: int = 1500) -> str:
    """Keep the paragraphs that describe the content; drop links, emails, promo lines, and short stubs.
    The sub-agent needs the substance of the idea, not the creator's funnel or contact details."""
    keep = []
    for para in re.split(r"\n\s*\n", (desc or "").strip()):
        lines = [ln for ln in para.splitlines() if not (_URL_RE.search(ln) or _EMAIL_RE.search(ln) or _PROMO_RE.search(ln))]
        text = " ".join(ln.strip() for ln in lines).strip()
        if len(text) >= 60:
            keep.append(text)
    out = "\n\n".join(keep)
    return (out[:max_chars] + " …") if len(out) > max_chars else (out or "(no usable description)")


def load_ideas(folder: Path) -> list[dict]:
    path = folder / "repeatability.csv"
    if not path.exists():
        sys.exit(f"{rel(path)} not found. Run `uv run python -m analysis.repeatability` first.")
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["repeatable"] == "True"]
    return sorted(rows, key=lambda r: (int(r["repeatability_score"]), float(r["outlier_multiple"])), reverse=True)


def load_evidence(folder: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    path = folder / "repeatability_matches.csv"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for m in csv.DictReader(f):
                if m["strong_hit"] == "True":
                    out[m["idea_video_id"]].append(m)
    for ms in out.values():
        ms.sort(key=lambda m: -int(m["match_views"]))
    return out


def brief_text(idea: dict, matches: list[dict], run_id: str, vcfg: dict) -> str:
    angle = vcfg["angle"] if vcfg["angle"] != "auto" else pick_angle(idea["idea_title"])
    desc = clean_description(idea["description"])
    evidence = "\n".join(f"- {m['match_channel']} — {int(m['match_views']):,} views — \"{m['match_title']}\"" for m in matches[:5]) or "- (no strong hits listed)"
    cust = []
    if vcfg.get("voice", "none") != "none":
        cust.append(f"- voice: {vcfg['voice']}" + (f" (voice_id {vcfg['voice_id']})" if vcfg.get("voice_id") else ""))
    if vcfg.get("music", "none") != "none":
        mood = vcfg.get("music_mood", "auto")
        cust.append(f"- music: {vcfg['music']} · mood: {'pick a mood that fits the idea and the script' if mood == 'auto' else mood}")
    customizations = "\n".join(cust) or "- none"
    return f"""# Brief: {idea['idea_title']}

- brief_id: {run_id}__{idea['source_video_id']}
- run_id: {run_id}
- created: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## The idea

**{idea['idea_title']}**

Make a short that delivers this idea as our own take. The ONE thing the viewer should walk away with
is the promise in that title.

## Why it works (evidence)

- The original did {int(idea['source_views']):,} views, {float(idea['outlier_multiple']):.1f}x its channel's median.
- {idea['repeatability_score']} other channels had a strong hit on the same topic in the last 6 months, e.g.:
{evidence}

## Source material (content only; links, contacts and promos removed — do not copy wording or name the creator)

Original title: {idea['idea_title']}
Topic query used: {idea['topic_query']}

Description:
{desc}

## Video spec (this is the confirmed brief — do not re-ask any of it)

- workflow: {vcfg['workflow']}
- flow: automation
- storyboard: no
- destination: {vcfg['destination']}
- aspect: {vcfg['aspect']}
- length: {vcfg['length']}
- language: {vcfg['language']}
- angle: {angle}
- message: "{idea['idea_title']}"

## Customizations

{customizations}

## Constraints

- Vertical, phone-first: big type, one idea per scene, hook in the first 2 seconds.
- No stock-photo look; typographic and graphic.
{"- No narration or voice-over: kinetic typography that lands the title as a hook, then one payoff line." if vcfg['workflow'] == 'motion-graphics' else "- Narrated: a tight script that fits the length; hook in the first line, one payoff at the end."}
- Do not mention or show the source creator.
- Deliver to output/{run_id}__{idea['source_video_id']}/video.mp4 with a SUMMARY.md carrying run_id {run_id}.
"""


def main(argv: list[str] | None = None) -> int:
    vcfg = pipeline_config.section("video")
    p = argparse.ArgumentParser(prog="python -m analysis.handoff", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", help="run to hand off from (default: current log stem)")
    p.add_argument("--idea", help="video ID of the idea to hand off (default: pipeline.toml [video] pick)")
    p.add_argument("--top", type=int, help="hand off the top N repeatable ideas")
    p.add_argument("--launch", action="store_true", help="run the sub-agent headlessly for each brief")
    args = p.parse_args(argv)
    run_id = args.run_id or current_run_id()
    folder = report_dir(run_id)
    agent_dir = (PROJECT_ROOT / vcfg["agent_dir"]).resolve()
    if not (agent_dir / "CLAUDE.md").exists():
        sys.exit(f"Video agent project not found at {agent_dir} (pipeline.toml [video] agent_dir).")

    ideas = load_ideas(folder)
    if not ideas:
        sys.exit("No repeatable ideas in this run.")
    pick = args.idea or (None if args.top else (vcfg["pick"] if vcfg["pick"] != "top" else None))
    if pick:
        chosen = [i for i in ideas if i["source_video_id"] == pick]
        if not chosen:
            sys.exit(f"Idea {pick} is not a repeatable idea in run {run_id}.")
    else:
        chosen = ideas[: args.top or 1]

    evidence = load_evidence(folder)
    briefs_dir = agent_dir / "briefs"; briefs_dir.mkdir(exist_ok=True)
    written = []
    for idea in chosen:
        name = f"{run_id}__{idea['source_video_id']}.md"
        (briefs_dir / name).write_text(brief_text(idea, evidence.get(idea["source_video_id"], []), run_id, vcfg), encoding="utf-8")
        written.append((idea, name))
        print(f"brief   {agent_dir.name}/briefs/{name}   <- {idea['idea_title'][:60]}")

    lines = [f"# Handoff to video agent · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"- **Run:** `{run_id}`", f"- **Agent project:** `{agent_dir}`",
             f"- **Spec:** {vcfg['workflow']} · {vcfg['destination']} · {vcfg['aspect']} · {vcfg['length']} · angle={vcfg['angle']}", "",
             "| Idea | Score | Multiple | Brief | Expected output |", "|---|---|---|---|---|"]
    for idea, name in written:
        lines.append(f"| {idea['idea_title'][:60].replace('|', '/')} | {idea['repeatability_score']} | {float(idea['outlier_multiple']):.1f}x | `briefs/{name}` | `output/{name[:-3]}/video.mp4` |")
    lines += ["", "Launch headlessly with:", "", "```bash"] + [f"scripts/run_video_agent.sh {name}" for _, name in written] + ["```"]
    (folder / "handoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"receipt {rel(folder / 'handoff.md')}")

    if args.launch:
        for _, name in written:
            print(f"\n=== launching video agent for {name} ===")
            subprocess.run([str(PROJECT_ROOT / "scripts" / "run_video_agent.sh"), name, str(agent_dir)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
