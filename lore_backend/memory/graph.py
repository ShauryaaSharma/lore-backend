"""The decision graph: which decisions overturned which, and what code each
one touched.

The other memory tiers answer "what did we decide" (semantic) and "when"
(episodic). Neither can answer "is that still true?" -- a PR that moved to
JWTs reads as the current decision forever, even after a later PR reverted
it. This tier makes that a query rather than a hope.

Status is computed, never stored. A decision is overturned when another
decision supersedes or reverts it, *unless that decision was itself
reverted*. Only a revert undoes: if B superseded A and C later superseded
B, A stays superseded, but reverting a revert restores the original.
Storing the result would mean recomputing every downstream node whenever an
edge arrives; the connected component is small enough to walk on read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from lore_backend.ingestion.links import OVERTURNING, Link, extract_links, split_stored_body
from lore_backend.storage.db import get_conn

logger = logging.getLogger("lore.memory.graph")

MAX_DEPTH = 10


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------

def index_decision(scope: str, source: str, *, title: str = "", body: str = "",
                   discussion: str = "", repo: str = "",
                   files: Optional[list[dict]] = None) -> list[Link]:
    """Re-derive one decision's outgoing edges from its text, and record the
    files it touched.

    Idempotent: a redelivered or edited PR replaces its edges rather than
    accumulating stale ones. `files=None` means "not fetched this time" and
    keeps whatever was recorded before; an empty list means "touched nothing".
    """
    links = extract_links(title=title, body=body, discussion=discussion,
                          repo=repo, self_source=source)
    with get_conn() as conn:
        conn.execute("delete from decision_links where scope = %s and from_source = %s",
                     (scope, source))
        for link in links:
            conn.execute(
                """
                insert into decision_links (scope, from_source, to_source, kind, evidence)
                values (%s, %s, %s, %s, %s)
                """,
                (scope, source, link.to_source, link.kind, link.evidence),
            )
        if files is not None:
            conn.execute("delete from decision_files where scope = %s and source = %s",
                         (scope, source))
            for f in files:
                path = (f.get("filename") or "").strip()
                if path:
                    conn.execute(
                        """
                        insert into decision_files (scope, source, path, change)
                        values (%s, %s, %s, %s) on conflict do nothing
                        """,
                        (scope, source, path, f.get("status") or ""),
                    )
        conn.commit()
    return links


def rebuild_links(scope: str) -> dict:
    """Re-index every stored decision's edges from its stored text. For data
    ingested before the graph existed, and after the extraction rules change.
    Files cannot be recovered from text, so they are left as they are."""
    with get_conn() as conn:
        rows = conn.execute(
            "select source, title, body, repo, kind from decision_events where scope = %s",
            (scope,),
        ).fetchall()

    edges = 0
    for source, title, body, repo, kind in rows:
        declared, discussion = split_stored_body(body) if kind == "pr" else (body, "")
        edges += len(index_decision(scope, source, title=title, body=declared,
                                    discussion=discussion, repo=repo))
    return {"decisions": len(rows), "edges": edges}


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@dataclass
class Status:
    source: str
    state: str                       # active | superseded | reverted | unknown
    overturned_by: Optional[str] = None
    evidence: str = ""


@dataclass
class Component:
    """The overturning edges reachable from some starting decisions, and the
    decisions on either end of them."""
    nodes: dict[str, dict] = field(default_factory=dict)   # source -> event (ingested only)
    sources: set[str] = field(default_factory=set)          # every source reached
    edges: list[dict] = field(default_factory=list)         # overturning edges only
    depth: dict[str, int] = field(default_factory=dict)
    cyclic: Optional[set[tuple[str, str]]] = None           # see _cyclic_edges


def component(scope: str, starts: list[str], max_depth: int = MAX_DEPTH) -> Component:
    """Walk supersedes/reverts edges in both directions from `starts`.

    Both directions because status needs what overturned a decision (and,
    recursively, whether *that* was overturned), and lineage needs what the
    decision itself replaced. The path array stops cycles: two PRs that each
    claim to supersede the other must not recurse forever.
    """
    comp = Component()
    if not starts:
        return comp

    with get_conn() as conn:
        rows = conn.execute(
            """
            with recursive walk(source, depth, path) as (
                select s, 0, array[s] from unnest(%(starts)s::text[]) as s
                union all
                select nxt.source, w.depth + 1, w.path || nxt.source
                from walk w
                join decision_links l
                  on l.scope = %(scope)s
                 and l.kind = any(%(kinds)s)
                 and (l.from_source = w.source or l.to_source = w.source)
                cross join lateral (
                    select case when l.from_source = w.source
                                then l.to_source else l.from_source end as source
                ) nxt
                where w.depth < %(max_depth)s
                  and not nxt.source = any(w.path)
            )
            select source, min(depth) from walk group by source
            """,
            {"starts": list(starts), "scope": scope, "kinds": list(OVERTURNING),
             "max_depth": max_depth},
        ).fetchall()
        comp.depth = {r[0]: int(r[1]) for r in rows}
        comp.sources = set(comp.depth)

        reached = list(comp.sources)
        for r in conn.execute(
            """
            select from_source, to_source, kind, evidence from decision_links
            where scope = %s and kind = any(%s)
              and from_source = any(%s) and to_source = any(%s)
            """,
            (scope, list(OVERTURNING), reached, reached),
        ).fetchall():
            comp.edges.append({"from": r[0], "to": r[1], "kind": r[2], "evidence": r[3]})

        comp.nodes = _events(conn, scope, reached)
    return comp


def statuses(scope: str, sources: list[str]) -> dict[str, Status]:
    """Whether each decision is still in force."""
    comp = component(scope, sources)
    return {s: _status(s, comp) for s in sources}


def decision(scope: str, source: str, max_depth: int = 5) -> Optional[dict]:
    """One decision with its status, its lineage, every edge in and out, and
    the files it touched. None when Lore has neither the decision nor any
    edge mentioning it.

    `max_depth` only trims the lineage shown. Status always walks the full
    depth: a revert five steps up the chain still decides what holds now."""
    comp = component(scope, [source])
    with get_conn() as conn:
        outgoing = conn.execute(
            "select to_source, kind, evidence from decision_links "
            "where scope = %s and from_source = %s order by kind, to_source",
            (scope, source),
        ).fetchall()
        incoming = conn.execute(
            "select from_source, kind, evidence from decision_links "
            "where scope = %s and to_source = %s order by kind, from_source",
            (scope, source),
        ).fetchall()
        files = conn.execute(
            "select path, change from decision_files where scope = %s and source = %s "
            "order by path",
            (scope, source),
        ).fetchall()
        linked = {r[0] for r in outgoing} | {r[0] for r in incoming}
        known = _events(conn, scope, list(linked | {source}))

    node = known.get(source)
    if node is None and not outgoing and not incoming:
        return None

    status = _status(source, comp)
    lineage = sorted(
        (s for s in comp.sources if s != source and comp.depth[s] <= max_depth),
        key=lambda s: (comp.depth[s], s),
    )
    return {
        "source": source,
        "ingested": node is not None,
        **_public(node),
        "status": status.state,
        "overturned_by": status.overturned_by,
        "overturned_evidence": status.evidence,
        "lineage": [
            {"source": s, "depth": comp.depth[s], "ingested": s in comp.nodes,
             "status": _status(s, comp).state, **_public(comp.nodes.get(s))}
            for s in lineage
        ],
        "links_out": [
            {"source": r[0], "kind": r[1], "evidence": r[2], "ingested": r[0] in known}
            for r in outgoing
        ],
        "links_in": [
            {"source": r[0], "kind": r[1], "evidence": r[2], "ingested": r[0] in known}
            for r in incoming
        ],
        "files": [{"path": r[0], "change": r[1]} for r in files],
    }


def decisions_touching(scope: str, path: str, limit: int = 20) -> list[dict]:
    """Decisions that touched a file, or anything under a directory, newest
    first, each with whether it still holds. A path ending in `/` is a
    directory prefix; anything else matches that exact file or, if it is a
    directory written without the slash, its contents."""
    path = path.strip().lstrip("/")
    prefix = _like_escape(path.rstrip("/")) + "/%"
    with get_conn() as conn:
        rows = conn.execute(
            r"""
            select f.source, array_agg(f.path order by f.path), max(e.occurred_at) as at
            from decision_files f
            join decision_events e on e.scope = f.scope and e.source = f.source
            where f.scope = %s and (f.path = %s or f.path like %s escape '\')
            group by f.source
            order by at desc nulls last, f.source
            limit %s
            """,
            (scope, path.rstrip("/"), prefix, limit),
        ).fetchall()
        events = _events(conn, scope, [r[0] for r in rows])

    found = statuses(scope, [r[0] for r in rows])
    return [
        {"source": r[0], **_public(events.get(r[0])), "paths": list(r[1]),
         "status": found[r[0]].state, "overturned_by": found[r[0]].overturned_by}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _status(source: str, comp: Component, visiting: frozenset = frozenset()) -> Status:
    """In force unless overturned by a decision that was not itself reverted.

    Three kinds of edge never count:
      * from a decision Lore has not ingested -- nothing is known about it;
      * from a PR stored without a merge date -- the backfill keeps closed
        PRs too, and an abandoned replacement replaced nothing;
      * on a cycle -- two decisions each claiming to replace the other is a
        data problem to surface, and picking a winner would make the answer
        depend on which one you asked about.
    """
    if source not in comp.nodes:
        return Status(source, "unknown")
    visiting = visiting | {source}
    cyclic = _cyclic_edges(comp)

    overturners = sorted(
        (e for e in comp.edges
         if e["to"] == source and e["from"] in comp.nodes
         and (e["from"], e["to"]) not in cyclic),
        key=lambda e: (comp.nodes[e["from"]].get("occurred_at") or "", e["from"]),
        reverse=True,
    )
    for edge in overturners:
        by = comp.nodes[edge["from"]]
        if by["kind"] == "pr" and not by["occurred_at"]:
            continue
        # Acyclic by construction above; `visiting` only guards the depth cap.
        if edge["from"] in visiting:
            continue
        if _status(edge["from"], comp, visiting).state != "reverted":
            state = "reverted" if edge["kind"] == "reverts" else "superseded"
            return Status(source, state, overturned_by=edge["from"], evidence=edge["evidence"])
    return Status(source, "active")


def _cyclic_edges(comp: Component) -> set[tuple[str, str]]:
    """Edges u->v where v can reach u again. Cached on the component: the
    graph is fixed for the lifetime of one read."""
    if comp.cyclic is not None:
        return comp.cyclic
    out: dict[str, set[str]] = {}
    for e in comp.edges:
        out.setdefault(e["from"], set()).add(e["to"])

    def reaches(start: str, goal: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(out.get(node, ()))
        return False

    comp.cyclic = {(e["from"], e["to"]) for e in comp.edges if reaches(e["to"], e["from"])}
    return comp.cyclic


def _events(conn, scope: str, sources: list[str]) -> dict[str, dict]:
    if not sources:
        return {}
    rows = conn.execute(
        """
        select source, kind, title, author, repo, url, occurred_at
        from decision_events where scope = %s and source = any(%s)
        """,
        (scope, sources),
    ).fetchall()
    return {
        r[0]: {"kind": r[1], "title": r[2], "author": r[3], "repo": r[4], "url": r[5],
               "occurred_at": r[6].isoformat() if r[6] else None}
        for r in rows
    }


def _public(event: Optional[dict]) -> dict:
    event = event or {}
    return {"title": event.get("title", ""), "repo": event.get("repo", ""),
            "url": event.get("url", ""), "occurred_at": event.get("occurred_at")}


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
