"""Procedural memory — prompts as reviewable files."""

from __future__ import annotations

from lore_backend.config import settings
from lore_backend.memory import procedural


def test_all_expected_prompts_exist():
    """A missing prompt file degrades answer quality silently, so make the
    absence loud here instead."""
    fingerprint = procedural.fingerprint()
    for name in ("system", "citation_policy", "tool_policy", "judge"):
        assert fingerprint[name]["loaded"], f"prompts/{name}.md is missing"


def test_system_prompt_interpolates_context():
    prompt = procedural.system_prompt("acme", "2026-08-20", 4)
    assert "acme" in prompt
    assert "2026-08-20" in prompt
    assert "at most 4" in prompt


def test_system_prompt_includes_all_three_policies():
    prompt = procedural.system_prompt("acme", "2026-08-20", 4)
    assert "Citation policy" in prompt
    assert "Tool policy" in prompt


def test_pipeline_prompt_omits_tool_policy():
    """The v1 path has no tools; telling it about a hop budget it can't spend
    is just noise in the context window."""
    prompt = procedural.pipeline_prompt("acme", "2026-08-20")
    assert "Citation policy" in prompt
    assert "Tool policy" not in prompt


def test_missing_prompt_returns_empty_rather_than_raising():
    assert procedural.load("definitely-not-a-prompt") == ""


def test_edits_are_picked_up_without_a_restart(tmp_path, monkeypatch):
    """Prompts are cached by mtime so a running dev server sees edits."""
    (tmp_path / "system.md").write_text("first version", encoding="utf-8")
    monkeypatch.setattr(settings, "prompts_dir", str(tmp_path))
    procedural._cache.clear()

    assert procedural.load("system") == "first version"

    path = tmp_path / "system.md"
    path.write_text("second version", encoding="utf-8")
    import os
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))

    assert procedural.load("system") == "second version"
    procedural._cache.clear()
