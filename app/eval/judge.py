"""LLM-as-judge scoring for /why answers.

The existing golden-set checks are substring matches: is `#482` in the
sources, does the answer contain "jwt". Cheap, deterministic, and shallow —
they pass an answer that cites the right PR and then explains it wrong.

The judge reads the question, the answer, and what was actually retrieved,
and scores three things (see prompts/judge.md). Its rubric is procedural
memory like every other prompt, so changing how answers are graded is a
reviewable diff.

**Observe-only by default** (`JUDGE_ENABLED=false`). A judge that hasn't
been shown to agree with human reading is a metric, not a gate; turning it
into CI policy before that is how teams end up optimising for a model's
taste. Record the scores first, gate once they've earned it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.memory import procedural

logger = logging.getLogger("lore.eval.judge")

_MAX = 6.0  # three dimensions, 0-2 each


@dataclass
class Verdict:
    grounded: int
    answers_question: int
    explains_why: int
    note: str = ""
    available: bool = True

    @property
    def total(self) -> int:
        return self.grounded + self.answers_question + self.explains_why

    @property
    def normalised(self) -> float:
        """0.0-1.0, so it sits alongside the other rates in the report."""
        return round(self.total / _MAX, 3)

    def as_dict(self) -> dict:
        return {"grounded": self.grounded, "answers_question": self.answers_question,
                "explains_why": self.explains_why, "score": self.normalised,
                "note": self.note, "available": self.available}


UNAVAILABLE = Verdict(0, 0, 0, note="judge unavailable", available=False)


def _extract_json(text: str) -> dict:
    """Models wrap JSON in prose and fences no matter how firmly you ask.
    Take the first object that parses rather than failing the whole run."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in judge reply: {text[:200]!r}")
    return json.loads(match.group(0))


def _clamp(value) -> int:
    try:
        return max(0, min(2, int(value)))
    except (TypeError, ValueError):
        return 0


def judge(question: str, answer: str, retrieved: list[dict]) -> Verdict:
    """Score one answer. Never raises — an unavailable judge yields an
    `available=False` verdict that the harness reports separately instead of
    silently averaging in as a zero."""
    if settings.mode != "live":
        return UNAVAILABLE

    rubric = procedural.load("judge")
    if not rubric:
        logger.warning("prompts/judge.md missing — skipping judge")
        return UNAVAILABLE

    context = "\n\n".join(
        f"[{h.get('source', '?')}] {(h.get('text') or '')[:800]}" for h in retrieved
    ) or "(nothing was retrieved)"

    payload = (f"Question:\n{question}\n\nAnswer:\n{answer}\n\n"
               f"Retrieved decisions:\n{context}")

    from groq import Groq

    try:
        client = Groq(api_key=settings.groq_api_key)
        completion = client.chat.completions.create(
            model=settings.judge_model,
            messages=[{"role": "system", "content": rubric},
                      {"role": "user", "content": payload}],
            temperature=0.0,  # a grader that drifts between runs isn't a grader
        )
        data = _extract_json(completion.choices[0].message.content or "")
    except Exception:
        logger.exception("judge call failed")
        return UNAVAILABLE

    return Verdict(
        grounded=_clamp(data.get("grounded")),
        answers_question=_clamp(data.get("answers_question")),
        explains_why=_clamp(data.get("explains_why")),
        note=str(data.get("note", ""))[:200],
    )
