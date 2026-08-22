"""The guardrail is the thing standing between a fluent answer and a sourced
one, so its edge cases are worth being explicit about."""

from __future__ import annotations

from lore_backend.agent import guardrail


def hit(source: str, text: str = "some decision text") -> dict:
    return {"source": source, "text": text, "metadata": {}}


def test_cited_answer_passes():
    result = guardrail.check(
        "We moved off sessions after a Redis failover [PR #482].",
        [hit("PR #482")],
    )
    assert result["status"] == "ok"
    assert result["matched"] == ["PR #482"]


def test_citation_with_extra_title_text_still_matches():
    """The model quotes the full source label it was shown; the guardrail
    shouldn't punish it for being more specific than the stored id."""
    result = guardrail.check(
        "Short-lived JWTs replaced sessions [PR #482 — Move to JWT access tokens].",
        [hit("PR #482")],
    )
    assert result["status"] == "ok"


def test_invented_citation_is_a_violation():
    """The failure this whole module exists for: a real-looking citation for
    a decision that was never retrieved."""
    result = guardrail.check(
        "We standardised on JWTs [PR #999].",
        [hit("PR #482")],
    )
    assert result["status"] == "violation"
    assert result["unknown"] == ["PR #999"]


def test_specific_claims_without_any_citation_are_rejected():
    result = guardrail.check(
        "We switched in PR #482 after the outage.",
        [hit("PR #482")],
    )
    assert result["status"] == "violation"
    assert "specific claims" in result["reason"]


def test_abstention_with_nothing_retrieved_is_allowed():
    """Saying "no record" is the correct answer, not a guardrail failure."""
    result = guardrail.check(
        "I don't have a recorded decision for that yet.", []
    )
    assert result["status"] == "abstain"
    assert result["ok"] is True


def test_confident_answer_with_nothing_retrieved_is_rejected():
    """Nothing was retrieved, so anything stated as fact came from the
    model's own weights — exactly what Lore must not ship."""
    result = guardrail.check(
        "You use JWTs because they scale better than server-side sessions.", []
    )
    assert result["status"] == "violation"


def test_abstaining_despite_retrieval_is_allowed():
    """Decisions came back but none of them answered the question. Judging
    them irrelevant is a legitimate call; forcing a citation would be worse."""
    result = guardrail.check(
        "The Canon has no record of that decision.", [hit("PR #100")]
    )
    assert result["status"] == "abstain"


def test_empty_answer_is_a_violation():
    assert guardrail.check("", [hit("PR #482")])["status"] == "violation"


def test_failure_message_names_what_was_found():
    message = guardrail.failure_message(
        {"status": "violation"}, [hit("PR #482"), hit("ADR-007")]
    )
    assert "PR #482" in message and "ADR-007" in message


def test_failure_message_without_retrieval_invites_ingestion():
    message = guardrail.failure_message({"status": "violation"}, [])
    assert "don't have a recorded decision" in message
