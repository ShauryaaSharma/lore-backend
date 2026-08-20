"""The summarizer agent — episodic → semantic.

Every merged PR dumps raw discussion into episodic memory. Indexing all of
it as semantic memory fills the vector store with bot noise, "LGTM", and
rebase chatter, and retrieval quality falls as the corpus grows: the store
gets bigger without getting more useful.

So a cheap model periodically reads the unconsolidated tail and rewrites it
as durable facts. Raw events stay in Postgres — nothing is lost, and the
distillation can be rerun if the prompt improves.

Deliberately the small model (`SUMMARIZER_MODEL`, Llama 3.1 8B). Compression
is not the task that needs the 70B, and spending the free-tier budget here
would starve the part users actually wait on.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.memory import episodic, semantic

logger = logging.getLogger("lore.memory.consolidate")

_PROMPT = """Rewrite this recorded engineering decision as a single durable fact.

Keep: the decision, the reason behind it, the constraint or trade-off that
forced it, and any person named as objecting or deciding.

Drop: greetings, "LGTM", CI output, bot comments, rebase and merge chatter,
and anything that only made sense on the day.

Write 1-3 sentences, in past tense, as a statement of record. Do not add a
preamble, do not restate the title, and do not invent anything that isn't
below.

--- {source} ---
{text}
"""


def _summarize_one(client, source: str, text: str) -> Optional[str]:
    try:
        completion = client.chat.completions.create(
            model=settings.summarizer_model,
            messages=[{"role": "user",
                       "content": _PROMPT.format(source=source, text=text[:6000])}],
            temperature=0.1,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("summarizer failed for %s", source)
        return None


def consolidate_scope(scope: str, limit: Optional[int] = None,
                      progress=None) -> dict:
    """Distil one tenant's unconsolidated events.

    Each event is summarised and written back over its own semantic entry
    (same `source`, so `remember` updates in place rather than leaving the
    raw version behind next to the distilled one). Failures leave the event
    unconsolidated so the next run retries it."""
    limit = limit or settings.consolidate_batch_size
    events = episodic.pending_consolidation(scope, limit)
    if not events:
        return {"scope": scope, "pending": 0, "consolidated": 0, "skipped": 0}

    if settings.mode != "live":
        return {"scope": scope, "pending": len(events), "consolidated": 0,
                "skipped": len(events), "note": "live mode required (set GROQ_API_KEY)"}

    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    done: list[str] = []
    skipped = 0

    for i, event in enumerate(events):
        source = event["source"]
        raw = f"{event.get('title', '')}\n{event.get('body', '')}".strip()
        if not raw:
            skipped += 1
            continue

        distilled = _summarize_one(client, source, raw)
        if not distilled:
            skipped += 1
            continue

        semantic.remember(scope, text=distilled, source=source, metadata={
            "title": (event.get("title") or "")[:80],
            "author": event.get("author", ""),
            "repo": event.get("repo", ""),
            "url": event.get("url", ""),
            "date": (event.get("occurred_at") or "")[:10],
            "distilled": True,
        })
        done.append(source)

        if progress:
            progress(i + 1, len(events))

    episodic.mark_consolidated(scope, done)
    logger.info("consolidated %d/%d events for %s", len(done), len(events), scope)
    return {"scope": scope, "pending": len(events), "consolidated": len(done),
            "skipped": skipped}


def due_scopes() -> list[tuple[str, int]]:
    """Tenants with enough unconsolidated events to be worth a run — so the
    job doesn't wake the LLM up for three comments."""
    return episodic.scopes_with_pending(settings.consolidate_after_n_events)
