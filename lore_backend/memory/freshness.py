"""Decision freshness: has the code moved on from a decision nobody overturned?

The graph's `status` comes only from what people declared -- "Supersedes
#12", "Reverts #12". That is the reliable half, and it misses the common
case: a team rewrites the auth module over three PRs and none of them says
it replaces the decision that shaped it. Asked "why sessions?", Lore would
still present that decision as current.

Freshness is the other half, and it is an inference, so it is kept apart
from `status` and never overrides it. A decision still in force is
*possibly outdated* when, after it merged:

  removed  a later merged PR deleted one of its files, or
  churn    later merged PRs changed at least `stale_min_file_share` of its
           files, across at least `stale_min_later_changes` PRs.

Later PRs that link to the decision in any way (a mention included) do not
count: their authors knew it existed and chose not to say it was replaced.
Unmerged PRs are not changes. Every flag carries the PRs and files behind
it, so a reader can check the claim instead of trusting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lore_backend.config import settings
from lore_backend.storage.db import get_conn

MAX_REASONS = 3


@dataclass
class LaterChange:
    source: str
    title: str
    occurred_at: Optional[str]
    paths: list[str]
    removed: list[str]


@dataclass
class Freshness:
    source: str
    state: str                                  # current | possibly_outdated
    signals: list[str] = field(default_factory=list)   # removed, churn
    files_changed: int = 0
    files_total: int = 0
    changed_by: list[LaterChange] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "signals": self.signals,
            "files_changed": self.files_changed,
            "files_total": self.files_total,
            "changed_by": [
                {"source": c.source, "title": c.title, "occurred_at": c.occurred_at,
                 "paths": c.paths, "removed": c.removed}
                for c in self.changed_by[:MAX_REASONS]
            ],
        }


def freshness(scope: str, sources: Optional[list[str]] = None) -> dict[str, Freshness]:
    """Freshness for `sources`, or for every decision in the scope with
    recorded files when `sources` is None. Decisions with no recorded files
    or no merge date cannot be judged and come back `current` with
    files_total 0 -- absence of evidence, not evidence of freshness."""
    with get_conn() as conn:
        totals = dict(conn.execute(
            """
            select f.source, count(*) from decision_files f
            join decision_events e on e.scope = f.scope and e.source = f.source
            where f.scope = %(scope)s and e.occurred_at is not null
              and (%(all)s or f.source = any(%(sources)s))
            group by f.source
            """,
            {"scope": scope, "all": sources is None, "sources": sources or []},
        ).fetchall())

        rows = conn.execute(
            """
            -- d: the decision being judged. f1: its files. f2: the same
            -- paths in a later decision. later: that decision's event.
            select d.source, f2.source, later.title, later.occurred_at,
                   array_agg(f2.path order by f2.path),
                   array_agg(f2.path order by f2.path) filter (where f2.change = 'removed')
            from decision_events d
            join decision_files f1 on f1.scope = d.scope and f1.source = d.source
            join decision_files f2 on f2.scope = d.scope and f2.path = f1.path
                                  and f2.source <> d.source
            join decision_events later on later.scope = d.scope and later.source = f2.source
            where d.scope = %(scope)s
              and (%(all)s or d.source = any(%(sources)s))
              and d.occurred_at is not null
              -- Strictly later, which also rules out unmerged PRs (no date).
              and later.occurred_at > d.occurred_at
              and not exists (
                  select 1 from decision_links l
                  where l.scope = d.scope
                    and ((l.from_source = f2.source and l.to_source = d.source)
                      or (l.from_source = d.source and l.to_source = f2.source)))
            group by d.source, f2.source, later.title, later.occurred_at
            """,
            {"scope": scope, "all": sources is None, "sources": sources or []},
        ).fetchall()

    changes: dict[str, list[LaterChange]] = {}
    for decision, later, title, occurred_at, paths, removed in rows:
        changes.setdefault(decision, []).append(LaterChange(
            source=later, title=title or "",
            occurred_at=occurred_at.isoformat() if occurred_at else None,
            paths=list(paths), removed=list(removed or [])))

    wanted = sources if sources is not None else list(totals)
    return {s: _judge(s, totals.get(s, 0), changes.get(s, [])) for s in wanted}


def _judge(source: str, total: int, later: list[LaterChange]) -> Freshness:
    later.sort(key=lambda c: (c.occurred_at or "", c.source), reverse=True)
    changed = {p for c in later for p in c.paths}
    signals = []
    if any(c.removed for c in later):
        signals.append("removed")
    if (total and len(changed) / total >= settings.stale_min_file_share
            and len(later) >= settings.stale_min_later_changes):
        signals.append("churn")
    return Freshness(
        source=source,
        state="possibly_outdated" if signals else "current",
        signals=signals,
        files_changed=len(changed),
        files_total=total,
        changed_by=later,
    )


def describe(f: Freshness) -> str:
    """One line for people and for the model: what changed, and by whom."""
    if f.state != "possibly_outdated":
        return ""
    by = ", ".join(c.source for c in f.changed_by[:MAX_REASONS])
    more = f" and {len(f.changed_by) - MAX_REASONS} more" if len(f.changed_by) > MAX_REASONS else ""
    parts = []
    if "removed" in f.signals:
        removed = sorted({p for c in f.changed_by for p in c.removed})
        parts.append(f"{len(removed)} of its files deleted since")
    if "churn" in f.signals:
        parts.append(f"{f.files_changed} of its {f.files_total} files changed since")
    return f"possibly outdated: {' and '.join(parts)} by {by}{more}, none of which said it replaced it"
