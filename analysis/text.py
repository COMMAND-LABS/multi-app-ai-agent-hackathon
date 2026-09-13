"""Tiny text helpers for topic matching based on titles + descriptions (stdlib only)."""

from __future__ import annotations

import re

STOPWORDS = set(
    """a an the and or but of to in on for with at by from as is are was were be been being this that these those it its
    i me my we our you your he she they them their his her him how what why when where which who whom whose will would
    can could should shall may might must do does did done just not no yes so than then too very s t ll re ve d m
    every all any some more most much many few new best top ultimate complete full guide tutorial explained
    2024 2025 2026 2027 vs vs. ft feat official video watch make made using use used get got one two three""".split()
)

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️]")
_PAREN_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")
_NONWORD_RE = re.compile(r"[^a-z0-9$'/ ]+")


def clean_title(title: str) -> str:
    """Strip emoji, bracketed asides, and noisy punctuation. Keeps the natural phrase."""
    t = _EMOJI_RE.sub(" ", title)
    t = _PAREN_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -:|,.!?")
    return t


def tokens(text: str) -> set[str]:
    t = _NONWORD_RE.sub(" ", _EMOJI_RE.sub(" ", (text or "").lower()))
    out = set()
    for w in t.split():
        w = w.strip("'/")
        if len(w) >= 3 and w not in STOPWORDS:
            out.add(w)
    return out


def topic_query(title: str, max_len: int = 80) -> str:
    """Search query for 'videos on the same general topic': the cleaned title, shortened."""
    q = clean_title(title)
    if len(q) > max_len:
        q = q[:max_len].rsplit(" ", 1)[0]
    return q


def similarity(source_title: str, source_desc: str, cand_title: str, cand_desc: str) -> float:
    """Share of the source title's keywords that appear in the candidate's title+description,
    blended with description-keyword overlap. 1.0 = every keyword of the source title present."""
    src_title = tokens(source_title)
    if not src_title:
        return 0.0
    cand = tokens(cand_title) | tokens(cand_desc)
    title_hit = len(src_title & cand) / len(src_title)
    src_desc = tokens(source_desc) - src_title
    desc_hit = len(src_desc & cand) / len(src_desc) if src_desc else 0.0
    return round(0.8 * title_hit + 0.2 * desc_hit, 3)
