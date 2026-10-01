"""Edge extraction: which sentences become graph edges, and which must not.

Every false positive here is a decision `/why` will wrongly call overturned,
so most of these tests are about what is ignored."""

from __future__ import annotations

import pytest

from lore_backend.ingestion.links import extract_links, normalize_source, split_stored_body

REPO = "acme/api"


def edges(**kw) -> set[tuple[str, str]]:
    kw.setdefault("repo", REPO)
    return {(link.kind, link.to_source) for link in extract_links(**kw)}


@pytest.mark.parametrize("phrase", [
    "Supersedes #12", "supersedes: #12", "Replaces #12", "This replaced PR #12",
    "Obsoletes #12", "Superseding pull request #12",
])
def test_supersede_phrasings(phrase):
    assert edges(body=phrase) == {("supersedes", "PR #12")}


def test_githubs_own_revert_pr_body():
    """What GitHub writes when you press the Revert button."""
    assert edges(title='Revert "Move to JWT"', body="Reverts acme/api#50") == {
        ("reverts", "PR #50")}


def test_reverting_a_commit():
    assert edges(body="This reverts commit 1A2B3C4D5E6F.") == {("reverts", "commit 1a2b3c4")}


def test_a_list_of_targets_after_one_verb():
    assert edges(body="Supersedes #12, #14 and acme/api#15.") == {
        ("supersedes", "PR #12"), ("supersedes", "PR #14"), ("supersedes", "PR #15")}


def test_full_pull_request_urls():
    body = "Replaces https://github.com/acme/api/pull/9"
    assert edges(body=body) == {("supersedes", "PR #9")}


def test_plain_mentions_are_references():
    assert edges(body="Follows the approach in #30.") == {("references", "PR #30")}


def test_closing_keywords_point_at_issues_not_decisions():
    assert edges(body="Fixes #40. Closes #41, resolves #42.") == set()


def test_other_repositories_are_ignored():
    """`PR #7` is only unique within one repository's numbering."""
    assert edges(body="Replaces other/repo#7, see https://github.com/other/repo/pull/8") == set()


def test_without_a_known_repo_qualified_references_are_kept():
    assert edges(body="Replaces other/repo#7", repo="") == {("supersedes", "PR #7")}


def test_a_decision_never_links_to_itself():
    assert edges(body="Supersedes #50 and #12", self_source="PR #50") == {
        ("supersedes", "PR #12")}


def test_superseded_by_is_not_read_backwards():
    """'Superseded by #99' says #99 replaced *this* one. Recording it as this
    one superseding #99 would invert history, so it stays a mention."""
    assert edges(body="Superseded by #99") == {("references", "PR #99")}


def test_review_discussion_cannot_overturn_anything():
    """A reviewer asking 'does this supersede #8?' is not a decision."""
    found = edges(body="Tightens session expiry.",
                  discussion="Does this supersede #8? Also see #77.")
    assert found == {("references", "PR #8"), ("references", "PR #77")}


def test_overturning_beats_a_mention_of_the_same_target():
    found = extract_links(body="Supersedes #12. Context in #12's thread.", repo=REPO)
    assert [(link.kind, link.to_source) for link in found] == [("supersedes", "PR #12")]


@pytest.mark.parametrize("text", ["&#123; entity", "issue/#5 path", "color #ff0000", "abc#12"])
def test_things_that_only_look_like_references(text):
    assert edges(body=text) == set()


def test_evidence_is_the_sentence_the_edge_came_from():
    [link] = extract_links(body="Context first. We supersede #12 because rotation hurt. More.",
                           repo=REPO)
    assert link.evidence == "We supersede #12 because rotation hurt"


@pytest.mark.parametrize("raw, expected", [
    ("482", "PR #482"), ("#482", "PR #482"), ("PR #482", "PR #482"), ("pr#482", "PR #482"),
    ("commit 1A2B3C4", "commit 1a2b3c4"), ("1a2b3c4d5e", "commit 1a2b3c4"),
    ("auth", None), ("", None), ("PR #", None),
])
def test_normalize_source(raw, expected):
    assert normalize_source(raw) == expected


def test_split_stored_body_matches_how_canon_stores_prs():
    stored = "PR #5: Move to JWT\n\nSupersedes #3\n\nDiscussion:\n[comment] @a: see #4"
    assert split_stored_body(stored) == ("PR #5: Move to JWT\n\nSupersedes #3",
                                         "[comment] @a: see #4")
    assert split_stored_body("no discussion") == ("no discussion", "")
