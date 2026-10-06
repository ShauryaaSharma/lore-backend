"""Where the non-Python data files live.

`prompts/` and `migrations/` sit at the repo root for a source checkout, but a
wheel has no repo root — the build copies them under the package instead (see
`[tool.hatch.build]` in pyproject.toml). Resolve the packaged copy first and
fall back to the checkout, so the same code works installed or from git.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


def data_dir(name: str) -> Path:
    """Locate a bundled data directory by name (`prompts`, `migrations`)."""
    packaged = PACKAGE_DIR / name
    if packaged.is_dir():
        return packaged
    return REPO_ROOT / name
