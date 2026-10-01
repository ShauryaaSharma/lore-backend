from lore_backend.eval.harness import run_eval


def test_golden_set_regression_gate():
    """Runs in MOCK mode (no API keys in CI) — a floor on `_retrieve_seed`
    keyword matching. If this drops, either the seed corpus or the mock
    retriever regressed."""
    report = run_eval()
    assert report["mode"] == "mock"
    assert report["hit_rate"] >= 0.9, report
    assert report["citation_accuracy"] >= 0.9, report
