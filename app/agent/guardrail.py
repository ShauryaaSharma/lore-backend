"""The citation guardrail.

The failure this exists to stop: the model retrieves six loosely-related
decisions, none of which answers the question, and writes a fluent paragraph
anyway — with a citation borrowed from whichever decision was nearest. The
answer looks sourced. It isn't.

So the check runs against what retrieval *actually returned*, not against
what the answer claims. Three outcomes:

  ok        — every citation in the answer maps to a retrieved decision.
  abstain   — the answer cites nothing and nothing was retrieved. Correct
              behaviour: the Canon has no record, and saying so is the right
              answer, not a failure.
  violation — the answer cites a source that was never retrieved, or makes
              specific claims with no citation at all while decisions *were*
              available. This one does not ship.

Deliberately not an LLM check. A guardrail that can hallucinate is not a
guardrail, and string matching against a known-good set is exactly the kind
of problem regexes are good at.
"""

from __future__ import annotations

import re

# "[PR #482]", "[ADR-007]", "[commit a1b2c3d]" — the bracketed form the
# citation policy asks for.
_CITATION = re.compile(r"\[([^\[\]]{2,80})\]")

# A claim specific enough to need a source: a PR/issue number, an ADR/RFC id,
# or a short hex sha. Prose without any of these ("we chose availability over
# consistency") is a summary, not a smuggled fact.
_SPECIFIC = re.compile(r"(#\d+|\b(?:ADR|RFC)-\d+\b|\b[0-9a-f]{7,40}\b)", re.IGNORECASE)

_ABSTAIN_MARKERS = (
    "no record", "not recorded", "don't have", "do not have", "nothing recorded",
    "isn't covered", "is not covered", "no decision", "hasn't been recorded",
)


def _normalise(label: str) -> str:
    return re.sub(r"[^a-z0-9#]+", "", (label or "").lower())


def extract_citations(answer: str) -> list[str]:
    return [m.group(1).strip() for m in _CITATION.finditer(answer or "")]


def looks_like_abstention(answer: str) -> bool:
    low = (answer or "").lower()
    return any(marker in low for marker in _ABSTAIN_MARKERS)


def check(answer: str, retrieved: list[dict]) -> dict:
    """Verify an answer against the decisions actually retrieved."""
    answer = (answer or "").strip()
    known = {_normalise(h.get("source", "")): h.get("source", "") for h in retrieved}
    known.pop("", None)
    citations = extract_citations(answer)

    matched: list[str] = []
    unknown: list[str] = []
    for raw in citations:
        norm = _normalise(raw)
        # A citation matches if it is, or contains, a known source label —
        # "[PR #482 — Move to JWT]" should satisfy a source of "PR #482".
        hit = next((src for key, src in known.items() if key and (key in norm or norm in key)), None)
        if hit:
            if hit not in matched:
                matched.append(hit)
        else:
            unknown.append(raw)

    if not answer:
        return _result("violation", matched, unknown, "empty answer")

    if unknown:
        return _result("violation", matched, unknown,
                       f"cites {unknown[0]!r}, which was never retrieved")

    if matched:
        return _result("ok", matched, unknown, "")

    # No citations at all from here down.
    if not retrieved:
        if looks_like_abstention(answer):
            return _result("abstain", matched, unknown, "")
        return _result("violation", matched, unknown,
                       "nothing was retrieved, so the answer must say the Canon has no record")

    if looks_like_abstention(answer):
        # Decisions were retrieved but the model judged them irrelevant. That
        # is a legitimate call, and forcing a citation would be worse.
        return _result("abstain", matched, unknown, "")

    if _SPECIFIC.search(answer):
        return _result("violation", matched, unknown,
                       "makes specific claims without citing a retrieved decision")

    return _result("violation", matched, unknown,
                   "decisions were retrieved but the answer cites none of them")


def _result(status: str, matched: list[str], unknown: list[str], reason: str) -> dict:
    return {"status": status, "ok": status in ("ok", "abstain"),
            "matched": matched, "unknown": unknown, "reason": reason}


def failure_message(result: dict, retrieved: list[dict]) -> str:
    """What the user sees when an answer is rejected.

    Saying "I found these but couldn't ground an answer in them" is more
    useful than silence, and far more useful than the unsourced answer we
    just threw away."""
    if retrieved:
        listed = ", ".join(dict.fromkeys(h.get("source", "?") for h in retrieved[:5]))
        return ("I couldn't ground an answer in the recorded decisions. The closest "
                f"records are {listed} — none of them clearly answers this, so rather "
                "than guess: the Canon doesn't have this decision yet.")
    return ("I don't have a recorded decision for that yet. Lore learns from every "
            "merged PR and `Why:` commit, so this gap closes as the team works.")
