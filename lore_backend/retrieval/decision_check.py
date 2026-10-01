"""The decision check: before a change is reviewed, surface the decisions
still in force behind the code it touches.

`/why` only helps someone who already suspects there is a reason. The
expensive case is the one nobody suspects -- a PR that quietly undoes a
decision whose author has moved on. This runs on every opened PR, so the
reason arrives at review time instead of after the outage it prevented.

No model in this path. Which decisions touched which files is a fact in the
graph; a reviewer can trust the list without wondering whether it was
paraphrased into something the decision never said.
"""

from __future__ import annotations

from lore_backend.ingestion.links import OVERTURNING, extract_links, pr_source
from lore_backend.memory import graph


def check(scope: str, files: list[str], *, title: str = "", body: str = "",
          repo: str = "", number: int | None = None, limit: int = 5) -> dict:
    """Decisions in force behind `files`, and which of them this change
    says it overturns. `number` is the change's own PR, never reported
    against itself."""
    self_source = pr_source(number, repo) if number else ""
    found = graph.decisions_for_files(scope, files, limit=limit, exclude=self_source)
    declared = {
        link.to_source: link.kind
        for link in extract_links(title=title, body=body, repo=repo, self_source=self_source)
        if link.kind in OVERTURNING
    }
    for d in found["decisions"]:
        d["declared"] = declared.get(d["source"])
    return {"files": len(set(files)), **found}


def render(result: dict) -> str:
    """Markdown for the PR comment. Empty when there is nothing to say: a
    comment that only reports the absence of decisions is noise on every
    PR that touches new code."""
    decisions = result.get("decisions") or []
    if not decisions:
        return ""

    # One line per decision plus an optional quote. GitHub joins an indented
    # plain line onto the list item above it, and folds a line that follows
    # a quote into the quote, so nothing else may sit under an item.
    lines = ["**Decisions behind the code this PR changes**", ""]
    for d in decisions:
        where = "same file" if d["match"] == "file" else "same directory"
        paths = ", ".join(f"`{p}`" for p in d["paths"][:4])
        if len(d["paths"]) > 4:
            paths += f" +{len(d['paths']) - 4} more"
        parts = [f"**{d['source']}**" + (f" — {d['title']}" if d.get("title") else "")
                 + (f" _(merged {d['occurred_at'][:10]})_" if d.get("occurred_at") else ""),
                 f"{where} {paths}"]
        if d.get("declared"):
            parts.append(f"**this PR says it {d['declared']} it**")
        elif d.get("freshness") == "possibly_outdated":
            # A reviewer should weigh this one as history in waiting, and
            # the author of this PR may be the one to say so.
            parts.append(f"⚠️ {d['freshness_note']}")
        lines.append("- " + " · ".join(parts))
        if d.get("summary"):
            lines.append(f"  > {d['summary']}")
    lines.append("")
    lines.append("_If this change replaces one of these, say so in the description "
                 "(\"Supersedes #N\") and Lore will mark it as history when this merges._")
    return "\n".join(lines)
