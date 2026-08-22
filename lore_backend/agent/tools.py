"""The agent's tools.

Two rules shape this module:

**Scope is bound, never passed.** Every tool closes over the scope resolved
from the caller's API key. The model cannot name a tenant, so no prompt —
hostile or merely confused — can read another team's Canon. This is why
tools are built per request instead of declared once at import.

**Every tool returns text plus a recorded hit.** The string goes back to the
model; the structured hit goes into a collector the guardrail later checks
the answer against. Without the second half, "cite your sources" is a
suggestion the model can satisfy by inventing a plausible PR number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lore_backend.config import settings
from lore_backend.memory import episodic, semantic

logger = logging.getLogger("lore.agent.tools")

_NOTHING = ("No decisions matched. Do not guess — either try one different "
            "angle, or say the Canon has no record of this.")


@dataclass
class Collector:
    """What retrieval actually returned this run."""
    hits: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def add_hit(self, *, source: str, text: str, metadata: Optional[dict] = None,
                score: float = 0.0) -> None:
        if any(h["source"] == source for h in self.hits):
            return
        self.hits.append({"source": source, "text": text,
                          "metadata": metadata or {}, "score": score})

    def note_call(self, name: str, args: dict, n_results: int) -> None:
        self.calls.append({"tool": name, "args": args, "results": n_results})


# --------------------------------------------------------------------------
# argument schemas — these become the model's tool signatures, so the
# descriptions are prompt text, not documentation
# --------------------------------------------------------------------------

class SearchCanonArgs(BaseModel):
    query: str = Field(description="What to look for, in the user's own words.")
    limit: int = Field(default=6, ge=1, le=20,
                       description="How many decisions to return.")


class RecentDecisionsArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)
    since_days: Optional[int] = Field(
        default=None, description="Only decisions from the last N days.")


class FetchPrArgs(BaseModel):
    repo: str = Field(description="Repository as owner/name, e.g. acme/api.")
    number: int = Field(description="Pull request number.")


class SearchCommitsArgs(BaseModel):
    query: str = Field(description="Text to find in commit messages.")
    repo: str = Field(default="", description="Optional owner/name to scope the search.")


class PostCommentArgs(BaseModel):
    repo: str = Field(description="Repository as owner/name.")
    number: int = Field(description="Issue or PR number.")
    body: str = Field(description="Comment body, markdown.")


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def _github_token(login: str) -> Optional[str]:
    from lore_backend.ingestion import github_client as gh
    from lore_backend.storage.queries import get_installation_id_for_account

    if not gh.app_configured():
        return None
    installation_id = get_installation_id_for_account(login)
    if not installation_id:
        return None
    return gh.installation_token(installation_id)


def build_tools(scope: str, login: str, collector: Collector,
                allow_writes: bool = False) -> list[StructuredTool]:

    def search_canon(query: str, limit: int = 6) -> str:
        """Search recorded decisions by meaning. Start here."""
        candidates = settings.rerank_candidates if settings.rerank_enabled else limit
        hits = semantic.search(scope, query, limit=max(candidates, limit))

        if settings.rerank_enabled and hits:
            from lore_backend.retrieval.rerank import rerank
            hits = rerank(query, hits, limit, lambda h: h.text)
        else:
            hits = hits[:limit]

        collector.note_call("search_canon", {"query": query, "limit": limit}, len(hits))
        if not hits:
            return _NOTHING

        lines = []
        for h in hits:
            collector.add_hit(source=h.source, text=h.text,
                              metadata=h.metadata, score=h.score)
            lines.append(_format_decision(h.source, h.text, h.metadata))
        return "\n\n".join(lines)

    def recent_decisions(limit: int = 5, since_days: Optional[int] = None) -> str:
        """Most recent decisions by date. Use for 'lately' or 'last month'
        questions — similarity search cannot order by time."""
        events = episodic.recent(scope, limit=limit, since_days=since_days)
        collector.note_call("recent_decisions",
                            {"limit": limit, "since_days": since_days}, len(events))
        if not events:
            return _NOTHING

        lines = []
        for e in events:
            meta = {"date": (e.get("occurred_at") or "")[:10], "repo": e.get("repo", ""),
                    "author": e.get("author", ""), "url": e.get("url", "")}
            body = f"{e.get('title', '')}\n{e.get('body', '')}".strip()
            collector.add_hit(source=e["source"], text=body, metadata=meta)
            lines.append(_format_decision(e["source"], body, meta))
        return "\n\n".join(lines)

    def fetch_pr_diff(repo: str, number: int) -> str:
        """Read a pull request straight from GitHub. Use when the question
        names a PR the Canon has no decision for."""
        token = _github_token(login)
        collector.note_call("fetch_pr_diff", {"repo": repo, "number": number}, 0)
        if not token:
            return ("GitHub is not connected for this account, so this PR can't be "
                    "read. Answer from the Canon or say it has no record.")

        owner, _, name = repo.partition("/")
        if not owner or not name:
            return "repo must be owner/name, e.g. acme/api."

        from lore_backend.ingestion import github_client as gh

        pr = gh.fetch_pr(token, owner, name, number)
        if not pr:
            return f"PR #{number} was not found in {repo}."

        files = gh.fetch_pr_files(token, owner, name, number)
        threads = gh.fetch_pr_threads(token, owner, name, number)

        from lore_backend.retrieval.summarize import strip_bot_noise

        source = f"PR #{number}"
        body = strip_bot_noise(pr.get("body") or "")
        parts = [f"{pr.get('title', '')}", body]
        if files:
            parts.append("Files: " + ", ".join(
                f"{f['filename']} (+{f['additions']}/-{f['deletions']})" for f in files[:12]))
        if threads:
            parts.append("Discussion:\n" + strip_bot_noise(threads)[:2000])
        text = "\n\n".join(p for p in parts if p.strip())

        meta = {"repo": repo, "url": pr.get("html_url", ""),
                "author": (pr.get("user") or {}).get("login", ""),
                "date": (pr.get("merged_at") or pr.get("created_at") or "")[:10],
                "live_fetch": True}
        collector.add_hit(source=source, text=text, metadata=meta)
        return _format_decision(source, text, meta)

    def search_commits(query: str, repo: str = "") -> str:
        """Search commit messages. Finds decisions recorded as a `Why:`
        trailer that never reached a PR discussion."""
        token = _github_token(login)
        if not token:
            collector.note_call("search_commits", {"query": query, "repo": repo}, 0)
            return ("GitHub is not connected for this account. Answer from the Canon "
                    "or say it has no record.")

        from lore_backend.ingestion import github_client as gh

        commits = gh.search_commits(token, query, repo=repo)
        collector.note_call("search_commits", {"query": query, "repo": repo}, len(commits))
        if not commits:
            return _NOTHING

        lines = []
        for c in commits:
            source = f"commit {c['sha']}"
            meta = {"repo": c["repo"], "date": c["date"],
                    "author": c["author"], "url": c["url"]}
            collector.add_hit(source=source, text=c["message"], metadata=meta)
            lines.append(_format_decision(source, c["message"], meta))
        return "\n\n".join(lines)

    def post_comment(repo: str, number: int, body: str) -> str:
        """Post a comment on a GitHub issue or PR. Only when explicitly
        asked."""
        collector.note_call("post_comment", {"repo": repo, "number": number}, 0)
        if not allow_writes:
            return ("Writing to GitHub is not enabled for this request. Tell the user "
                    "what you would have posted instead of posting it.")
        token = _github_token(login)
        if not token:
            return "GitHub is not connected for this account."
        owner, _, name = repo.partition("/")
        from lore_backend.ingestion import github_client as gh

        ok = gh.post_issue_comment(token, owner, name, number, body)
        return "Comment posted." if ok else "GitHub rejected the comment."

    tools = [
        StructuredTool.from_function(
            func=search_canon, name="search_canon",
            description="Search this team's recorded decisions by meaning. Always try this first.",
            args_schema=SearchCanonArgs),
        StructuredTool.from_function(
            func=recent_decisions, name="recent_decisions",
            description="List the most recent decisions by date. Use for questions about "
                        "what happened lately, which similarity search cannot answer.",
            args_schema=RecentDecisionsArgs),
        StructuredTool.from_function(
            func=fetch_pr_diff, name="fetch_pr_diff",
            description="Read a specific pull request from GitHub when the Canon has no "
                        "decision for it.",
            args_schema=FetchPrArgs),
        StructuredTool.from_function(
            func=search_commits, name="search_commits",
            description="Search commit messages on GitHub for a recorded reason.",
            args_schema=SearchCommitsArgs),
    ]
    if allow_writes:
        tools.append(StructuredTool.from_function(
            func=post_comment, name="post_comment",
            description="Post a comment on a GitHub issue or PR. Only when the user asked "
                        "for something to be written back.",
            args_schema=PostCommentArgs))
    return tools


def _format_decision(source: str, text: str, metadata: dict) -> str:
    """One decision, rendered for the model. The source label leads because
    that is the string the answer has to cite verbatim."""
    tags = " · ".join(t for t in (
        f"repo {metadata.get('repo')}" if metadata.get("repo") else "",
        f"date {metadata.get('date')}" if metadata.get("date") else "",
        f"by {metadata.get('author')}" if metadata.get("author") else "",
    ) if t)
    head = f"[{source}]" + (f" ({tags})" if tags else "")
    return f"{head}\n{(text or '').strip()[:1500]}"
