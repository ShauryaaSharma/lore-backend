"""Procedural memory — how the agent behaves.

These live as files under `prompts/`, not as rows in a table, so a change to
the persona or the citation rules shows up in `git diff`, gets reviewed in a
PR, and can be rolled back like any other code. A prompt sitting in a
database is a config change nobody can review.

Files are read once and cached, keyed by mtime — editing a prompt during
`uvicorn --reload` development picks up immediately without a restart, while
production pays one read per file per process.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lore_backend.config import settings
from lore_backend.paths import data_dir

logger = logging.getLogger("lore.memory.procedural")

_cache: dict[str, tuple[float, str]] = {}


def prompts_dir() -> Path:
    p = Path(settings.prompts_dir)
    if p.is_absolute():
        return p
    return data_dir(settings.prompts_dir)


def load(name: str) -> str:
    """Read `prompts/<name>.md`. Missing files return "" rather than raising:
    a deleted prompt should degrade the answer, not take down /why."""
    path = prompts_dir() / f"{name}.md"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.warning("procedural memory %s not found at %s", name, path)
        return ""

    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]

    text = path.read_text(encoding="utf-8")
    _cache[name] = (mtime, text)
    return text


def system_prompt(login: str, today: str, max_hops: int) -> str:
    """The full behavioural prompt: persona + citation policy + tool policy.

    Composed at call time rather than stored pre-joined so each file stays
    independently reviewable, and so a surface that doesn't have tools (the
    v1 fallback path) can leave the tool policy out."""
    parts = [
        load("system").format(login=login, today=today),
        load("citation_policy"),
        load("tool_policy").format(max_hops=max_hops),
    ]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def pipeline_prompt(login: str, today: str) -> str:
    """Same persona and citation rules, no tool policy — for the v1
    straight-line path, which has no tools to reason about."""
    parts = [
        load("system").format(login=login, today=today),
        load("citation_policy"),
    ]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def fingerprint() -> dict:
    """What's loaded right now, for /health and for stamping a trace — so a
    bad answer can be tied back to the exact prompt version that produced
    it."""
    out = {}
    for name in ("system", "citation_policy", "tool_policy", "judge"):
        text = load(name)
        out[name] = {"chars": len(text), "loaded": bool(text)}
    return out
