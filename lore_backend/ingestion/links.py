"""Read decision-to-decision links out of PR and commit text.

Deterministic on purpose. An LLM would catch more phrasings, but a graph
edge that says one decision overturned another changes what `/why` is
allowed to present as current, and that is not a claim to hallucinate. A
regex either matched a sentence a human wrote or it did not, and the
sentence is kept as evidence so every edge can be checked by reading it.

Three kinds of edge:

  supersedes  "Supersedes #12", "Replaces #12", "Obsoletes #12"
  reverts     "Reverts acme/api#12" (GitHub's own revert PR body),
              "This reverts commit 1a2b3c4"
  references  any other mention of a PR in the same repository

Overturning edges are read from the title and body only, never from the
review discussion: "does this supersede #12?" in a comment is a question,
not a decision. Plain references are read from everything.

Closing keywords ("Fixes #12") are skipped. They point at issues, and an
issue is not a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OVERTURNING = ("supersedes", "reverts")

# One reference to a PR. Bare `#12` must not follow a word character, `&`
# (an HTML entity like &#123;) or `/` (part of a URL path handled below).
_REF = (
    r"(?:https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/(?:pull|issues)/(?P<url_num>\d+)"
    r"|(?P<qual_repo>[\w.-]+/[\w.-]+)#(?P<qual_num>\d+)"
    r"|(?<![\w&/])#(?P<bare_num>\d+))"
)
_REF_RE = re.compile(_REF, re.IGNORECASE)
# The same shape without named groups, for repeating inside a larger
# pattern. The run is re-scanned with _REF_RE to pull the numbers out.
_REF_ANON = re.sub(r"\(\?P<\w+>", "(?:", _REF)

_SUPERSEDE_VERBS = r"supersed(?:es|ed|ing|e)|replac(?:es|ed|ing|e)|obsolet(?:es|ed|ing|e)"
_REVERT_VERBS = r"revert(?:s|ed|ing)?"
# "Supersedes #12, #14 and acme/api#15": a verb, then a run of references.
_PREFIX = r"(?:(?:PR|pull request)\s*)?"
_REF_RUN = rf"{_PREFIX}{_REF_ANON}(?:\s*(?:,|and|&)\s*{_PREFIX}{_REF_ANON})*"
_VERB_RE = re.compile(
    rf"\b(?P<verb>{_SUPERSEDE_VERBS}|{_REVERT_VERBS})\b[:\s]+(?P<run>{_REF_RUN})",
    re.IGNORECASE,
)
_REVERT_COMMIT_RE = re.compile(r"\breverts?\s+commit\s+(?P<sha>[0-9a-f]{7,40})\b", re.IGNORECASE)
_CLOSING_RE = re.compile(
    rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[:\s]+(?P<run>{_REF_RUN})", re.IGNORECASE
)
_SOURCE_RE = re.compile(r"^(?:pr\s*)?#?\s*(\d+)$", re.IGNORECASE)
_COMMIT_SOURCE_RE = re.compile(r"^(?:commit\s+)?([0-9a-f]{7,40})$", re.IGNORECASE)


@dataclass(frozen=True)
class Link:
    to_source: str
    kind: str
    evidence: str


def pr_source(number: int | str) -> str:
    """The source label a merged PR is stored under (see canon.inscribe_pr)."""
    return f"PR #{int(number)}"


def commit_source(sha: str) -> str:
    """The source label a commit is stored under (see canon.inscribe_commit)."""
    return f"commit {sha[:7].lower()}"


def normalize_source(raw: str) -> str | None:
    """Accept the ways people write a decision id: `482`, `#482`, `PR #482`,
    `pr#482`, `commit 1a2b3c4`, a bare sha. Returns the stored label, or None
    when it is none of those."""
    text = (raw or "").strip()
    if m := _SOURCE_RE.match(text):
        return pr_source(m.group(1))
    if m := _COMMIT_SOURCE_RE.match(text):
        return commit_source(m.group(1))
    return None


def extract_links(*, title: str = "", body: str = "", discussion: str = "",
                  repo: str = "", self_source: str = "") -> list[Link]:
    """Every link this decision's text declares, strongest kind per target.

    `repo` is the decision's own owner/name. References qualified with a
    different repository are dropped: a decision source is only unique
    within one repository's PR numbering.
    """
    declared = f"{title}\n{body}"
    found: dict[str, Link] = {}

    def keep(to_source: str, kind: str, evidence: str) -> None:
        if to_source == self_source:
            return
        current = found.get(to_source)
        # An overturning edge beats a plain mention of the same target.
        if current is None or (current.kind == "references" and kind != "references"):
            found[to_source] = Link(to_source, kind, _snippet(evidence))

    for m in _VERB_RE.finditer(declared):
        kind = "reverts" if m.group("verb").lower().startswith("revert") else "supersedes"
        for number in _numbers_in(m.group("run"), repo):
            keep(pr_source(number), kind, _sentence(declared, m.start(), m.end()))

    for m in _REVERT_COMMIT_RE.finditer(declared):
        keep(commit_source(m.group("sha")), "reverts", _sentence(declared, m.start(), m.end()))

    closing = {
        n for m in _CLOSING_RE.finditer(f"{declared}\n{discussion}")
        for n in _numbers_in(m.group("run"), repo)
    }
    everything = f"{declared}\n{discussion}"
    for m in _REF_RE.finditer(everything):
        number = _number_if_same_repo(m, repo)
        if number is None or number in closing:
            continue
        keep(pr_source(number), "references", _sentence(everything, m.start(), m.end()))

    return sorted(found.values(), key=lambda link: (link.kind, link.to_source))


def split_stored_body(text: str) -> tuple[str, str]:
    """Undo canon.inscribe_pr's layout ("PR #N: title\\n\\nbody\\n\\nDiscussion:\\n
    threads") so a stored event can be re-indexed with the same rules as a
    fresh one. Returns (declared text, discussion)."""
    head, sep, discussion = (text or "").partition("\n\nDiscussion:\n")
    return head, discussion if sep else ""


def _numbers_in(run: str, repo: str) -> list[int]:
    return [n for m in _REF_RE.finditer(run) if (n := _number_if_same_repo(m, repo)) is not None]


def _number_if_same_repo(m: re.Match, repo: str) -> int | None:
    if m.group("bare_num"):
        return int(m.group("bare_num"))
    qualified = m.group("url_repo") or m.group("qual_repo")
    number = m.group("url_num") or m.group("qual_num")
    if repo and qualified.lower() != repo.lower():
        return None
    return int(number)


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence or line around a match, so the edge carries its reason."""
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start))
    right_candidates = [i for i in (text.find("\n", end), text.find(". ", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1:right + 1].strip(" .\n")


def _snippet(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"
