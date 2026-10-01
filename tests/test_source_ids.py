"""Repository-qualified decision ids.

PRs used to be stored as `PR #482`, unique per account. One account spans
many repositories, so the second #482 silently overwrote the first. These
tests pin the fix, the migration of existing data, and everything that has
to agree on the new label: the vector store, the guardrail and resolution of
the bare numbers people actually type."""

from __future__ import annotations

from pathlib import Path

import pytest

from lore_backend.agent import guardrail
from lore_backend.agent.tools import Collector, build_tools
from lore_backend.config import settings
from lore_backend.memory import episodic, graph, semantic
from lore_backend.retrieval import canon
from lore_backend.storage.db import get_conn

SCOPE = "gh:acme"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0004_repo_qualified_sources.sql"


@pytest.fixture
def no_vectors(monkeypatch):
    monkeypatch.setattr(canon.semantic, "remember", lambda *a, **k: None)


def inscribe(number: int, repo: str, body: str = "") -> None:
    canon.inscribe_pr(SCOPE, number=number, title=f"{repo} #{number}", body=body, threads="",
                      author="a", repo_full=repo, url="", merged_at="2026-01-01T00:00:00Z")


def sources() -> list[str]:
    with get_conn() as conn:
        return sorted(r[0] for r in conn.execute(
            "select source from decision_events where scope = %s", (SCOPE,)).fetchall())


# ------------------------------------------------------------------ the bug

def test_same_number_in_two_repositories_is_two_decisions(no_vectors):
    inscribe(5, "acme/api")
    inscribe(5, "acme/web")
    assert sources() == ["acme/api#5", "acme/web#5"]


def test_repository_case_does_not_make_a_second_decision(no_vectors):
    inscribe(5, "Acme/API")
    inscribe(5, "acme/api")
    assert sources() == ["acme/api#5"]


def test_a_bare_reference_links_within_its_own_repository(no_vectors):
    inscribe(5, "acme/api")
    inscribe(5, "acme/web")
    inscribe(6, "acme/web", "Supersedes #5")
    assert graph.statuses(SCOPE, ["acme/api#5", "acme/web#5"]) == {
        "acme/api#5": graph.Status("acme/api#5", "active"),
        "acme/web#5": graph.Status("acme/web#5", "superseded", "acme/web#6", "Supersedes #5"),
    }


def test_cross_repository_links_resolve(no_vectors):
    inscribe(5, "acme/api")
    inscribe(9, "acme/web", "Replaces acme/api#5")
    assert graph.statuses(SCOPE, ["acme/api#5"])["acme/api#5"].overturned_by == "acme/web#9"


# --------------------------------------------------------------- resolution

def test_a_bare_number_resolves_when_one_repository_has_it(no_vectors):
    inscribe(5, "acme/api")
    assert graph.resolve_source(SCOPE, "PR #5") == "acme/api#5"


def test_a_bare_number_known_only_from_an_edge_resolves(no_vectors):
    inscribe(9, "acme/web", "Supersedes #5")
    assert graph.resolve_source(SCOPE, "PR #5") == "acme/web#5"


def test_a_bare_number_two_repositories_have_is_ambiguous(no_vectors):
    inscribe(5, "acme/api")
    inscribe(5, "acme/web")
    with pytest.raises(graph.AmbiguousSource) as exc:
        graph.resolve_source(SCOPE, "PR #5")
    assert exc.value.candidates == ["acme/api#5", "acme/web#5"]


def test_a_number_that_only_shares_digits_is_not_a_candidate(no_vectors):
    inscribe(15, "acme/api")
    inscribe(5, "acme/web")
    assert graph.resolve_source(SCOPE, "PR #5") == "acme/web#5"


@pytest.mark.parametrize("label", ["acme/api#5", "commit 1a2b3c4", "PR #404"])
def test_qualified_commit_and_unknown_labels_pass_through(label):
    assert graph.resolve_source(SCOPE, label) == label


def test_api_asks_which_repository_when_ambiguous(client, no_vectors):
    inscribe(5, "acme/api")
    inscribe(5, "acme/web")
    response = client.get("/v1/graph/decision", params={"source": "#5", "user_id": SCOPE})
    assert response.status_code == 409
    assert response.json()["detail"]["candidates"] == ["acme/api#5", "acme/web#5"]

    response = client.get("/v1/graph/decision", params={"source": "acme/web#5", "user_id": SCOPE})
    assert response.status_code == 200
    assert response.json()["repo"] == "acme/web"


def test_agent_tool_asks_which_repository_when_ambiguous(no_vectors):
    inscribe(5, "acme/api")
    inscribe(5, "acme/web")
    collector = Collector()
    tool = {t.name: t for t in build_tools(SCOPE, "acme", collector)}["decision_status"]

    text = tool.invoke({"source": "PR #5"})

    assert "acme/api#5, acme/web#5" in text
    assert collector.hits == []


# ---------------------------------------------------------------- guardrail

def hits(*labels: str) -> list[dict]:
    return [{"source": label, "text": "decision text", "metadata": {}} for label in labels]


def test_qualified_citation():
    assert guardrail.check("JWTs [acme/api#482].", hits("acme/api#482"))["status"] == "ok"


def test_unqualified_citation_of_the_one_retrieved_482():
    result = guardrail.check("JWTs [PR #482].", hits("acme/api#482"))
    assert (result["status"], result["matched"]) == ("ok", ["acme/api#482"])


def test_unqualified_citation_with_two_retrieved_482s_says_nothing():
    result = guardrail.check("JWTs [PR #482].", hits("acme/api#482", "acme/web#482"))
    assert result["status"] == "violation"


@pytest.mark.parametrize("citation, retrieved", [
    ("[PR #48]", "PR #482"),        # a prefix of the digits used to pass
    ("[acme/api#48]", "acme/api#482"),
    ("[#482]", "acme/api#1482"),
    ("[PR]", "PR #482"),
    ("[acme]", "acme/api#482"),
])
def test_citations_that_only_overlap_a_retrieved_label_are_violations(citation, retrieved):
    assert guardrail.check(f"JWTs {citation}.", hits(retrieved))["status"] == "violation"


@pytest.mark.parametrize("citation, retrieved", [
    ("[ADR-007]", "ADR-007 — service boundaries"),
    ("[#482]", "#482 — Move to JWT access tokens"),
    ("[commit a1b2c3d]", "commit a1b2c3d"),
])
def test_seed_and_commit_labels_still_match(citation, retrieved):
    assert guardrail.check(f"We did this {citation}.", hits(retrieved))["status"] == "ok"


# ---------------------------------------------------------------- migration

def run_migration() -> None:
    with get_conn() as conn:
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
        conn.commit()


def old_event(source: str, repo: str, kind: str = "pr") -> None:
    episodic.record_event(SCOPE, kind=kind, source=source, title=source, body=source,
                          repo=repo, occurred_at="2026-01-01T00:00:00Z")


def old_link(from_source: str, to_source: str, kind: str = "supersedes") -> None:
    with get_conn() as conn:
        conn.execute("insert into decision_links (scope, from_source, to_source, kind) "
                     "values (%s, %s, %s, %s)", (SCOPE, from_source, to_source, kind))
        conn.commit()


def test_migration_renames_old_pr_decisions_and_everything_pointing_at_them():
    old_event("PR #5", "Acme/API")
    old_event("PR #6", "Acme/API")
    old_event("commit abc1234", "", kind="commit")
    old_link("PR #6", "PR #5")
    old_link("PR #6", "PR #77", "references")       # target never ingested
    old_link("commit abc1234", "PR #5", "references")
    with get_conn() as conn:
        conn.execute("insert into decision_files (scope, source, path) values (%s, %s, %s)",
                     (SCOPE, "PR #5", "src/a.py"))
        conn.commit()

    run_migration()

    assert sources() == ["acme/api#5", "acme/api#6", "commit abc1234"]
    with get_conn() as conn:
        links = sorted(conn.execute(
            "select from_source, to_source from decision_links where scope = %s",
            (SCOPE,)).fetchall())
        files = conn.execute("select source from decision_files where scope = %s",
                             (SCOPE,)).fetchall()
        renames = sorted(conn.execute(
            "select old_source, new_source, applied_at from source_renames").fetchall())
    assert links == [("acme/api#6", "acme/api#5"), ("acme/api#6", "acme/api#77"),
                     ("commit abc1234", "acme/api#5")]
    assert files == [("acme/api#5",)]
    assert renames == [("PR #5", "acme/api#5", None), ("PR #6", "acme/api#6", None)]
    assert graph.statuses(SCOPE, ["acme/api#5"])["acme/api#5"].overturned_by == "acme/api#6"


def test_migration_leaves_prs_without_a_repository_alone():
    old_event("PR #5", "")
    run_migration()
    assert sources() == ["PR #5"]


# ---------------------------------------------------------- vector renames

def pending(old: str, new: str) -> None:
    with get_conn() as conn:
        conn.execute("insert into source_renames (scope, old_source, new_source) "
                     "values (%s, %s, %s)", (SCOPE, old, new))
        conn.commit()


def applied() -> list[tuple]:
    with get_conn() as conn:
        return conn.execute("select old_source, applied_at is not null "
                            "from source_renames order by old_source").fetchall()


@pytest.fixture
def pgvector(monkeypatch):
    monkeypatch.setattr(settings, "vector_store", "pgvector")
    monkeypatch.setattr(settings, "embedder_dims", 3)
    semantic.reset_store_cache()
    store = semantic.get_store()
    yield store
    with get_conn() as conn:
        conn.execute(f"drop table if exists {store.table}")
        conn.commit()
    semantic.reset_store_cache()


def put_pg(store, source: str, text: str = "decision") -> None:
    import json

    with get_conn() as conn:
        conn.execute(
            f"insert into {store.table} (id, scope, doc_id, text, metadata, embedding) "
            "values (%s, %s, %s, %s, %s, '[1,0,0]')",
            (semantic.point_id(SCOPE, semantic.doc_id_for(source)), SCOPE,
             semantic.doc_id_for(source), text, json.dumps({"source": source})))
        conn.commit()


def test_nothing_pending_does_not_open_the_store(monkeypatch):
    monkeypatch.setattr(semantic, "get_store", lambda: pytest.fail("opened the store"))
    assert semantic.apply_source_renames() == {"renamed": 0, "missing": 0, "failed": 0}


def test_pgvector_rename_keeps_the_vector_and_relabels(pgvector):
    put_pg(pgvector, "PR #5")
    pending("PR #5", "acme/api#5")

    assert semantic.apply_source_renames() == {"renamed": 1, "missing": 0, "failed": 0}

    [hit] = pgvector.all(SCOPE)
    assert (hit.id, hit.source) == ("acme-api-5", "acme/api#5")
    assert applied() == [("PR #5", True)]
    assert semantic.apply_source_renames()["renamed"] == 0, "applied renames are not redone"


def test_pgvector_rename_after_reingest_drops_the_stale_point(pgvector):
    put_pg(pgvector, "PR #5", text="old")
    put_pg(pgvector, "acme/api#5", text="fresh")
    pending("PR #5", "acme/api#5")

    semantic.apply_source_renames()

    assert [h.text for h in pgvector.all(SCOPE)] == ["fresh"]


def test_rename_with_nothing_in_the_store_is_counted_not_failed(pgvector):
    pending("PR #5", "acme/api#5")
    assert semantic.apply_source_renames() == {"renamed": 0, "missing": 1, "failed": 0}


def test_a_failed_rename_is_retried_next_time(monkeypatch):
    class Broken:
        def rename(self, *a):
            raise RuntimeError("store down")

    monkeypatch.setattr(semantic, "get_store", lambda: Broken())
    pending("PR #5", "acme/api#5")

    assert semantic.apply_source_renames()["failed"] == 1
    assert applied() == [("PR #5", False)]


def test_qdrant_rename(monkeypatch, tmp_path):
    from qdrant_client import models

    monkeypatch.setattr(settings, "vector_store", "qdrant")
    monkeypatch.setattr(settings, "qdrant_url", "")
    monkeypatch.setattr(settings, "qdrant_path", str(tmp_path / "qdrant"))
    monkeypatch.setattr(settings, "embedder_dims", 3)
    semantic.reset_store_cache()
    store = semantic.get_store()

    def put(source: str, text: str) -> None:
        doc = semantic.doc_id_for(source)
        store.client.upsert(collection_name=store.collection, points=[models.PointStruct(
            id=semantic.point_id(SCOPE, doc), vector=[0.0, 1.0, 0.0],
            payload={"scope": SCOPE, "doc_id": doc, "text": text, "source": source})])

    try:
        put("PR #5", "moved")
        put("PR #6", "stale")
        put("acme/api#6", "fresh")
        pending("PR #5", "acme/api#5")
        pending("PR #6", "acme/api#6")

        assert semantic.apply_source_renames() == {"renamed": 2, "missing": 0, "failed": 0}

        stored = {h.source: h.text for h in store.all(SCOPE)}
        assert stored == {"acme/api#5": "moved", "acme/api#6": "fresh"}
        [point] = store.client.retrieve(store.collection,
                                        ids=[semantic.point_id(SCOPE, "acme-api-5")],
                                        with_vectors=True)
        assert list(point.vector) == [0.0, 1.0, 0.0]
    finally:
        store.client.close()
        semantic.reset_store_cache()
