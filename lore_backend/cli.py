"""Console entry points for an installed `lore-backend`.

A pip install has no docker-compose and no repo checkout to `python -m` from,
so the two long-running processes each get a script. Both are thin: all the
configuration still comes from the environment via `lore_backend.config`.
"""

from __future__ import annotations

import argparse
import os

from lore_backend import __version__


def serve() -> None:
    """Run the API server (`lore-backend`)."""
    import uvicorn

    parser = argparse.ArgumentParser(prog="lore-backend", description="Run the Lore API server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--version", action="version", version=f"lore-backend {__version__}")
    args = parser.parse_args()

    uvicorn.run("lore_backend.main:app", host=args.host, port=args.port, reload=args.reload)


def worker() -> None:
    """Run the background job worker (`lore-backend-worker`)."""
    from lore_backend.jobs.worker import run_forever

    parser = argparse.ArgumentParser(
        prog="lore-backend-worker", description="Run the Lore background job worker."
    )
    parser.add_argument("--version", action="version", version=f"lore-backend {__version__}")
    parser.parse_args()

    run_forever()
