"""PR summarization: strip bot noise, ask Groq for an (understood, remember)
pair, and render the per-PR comment. Ported near-verbatim from the prototype
— this logic (and its regexes) is already correct; only the Groq call gained
a circuit breaker so a Groq outage doesn't hang comment-posting."""

from __future__ import annotations

import re

from app.config import settings
from app.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError

_groq_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    cooldown_seconds=settings.circuit_breaker_cooldown_seconds,
    name="groq",
)


def strip_bot_noise(text: str) -> str:
    """Remove machine-generated boilerplate (Vercel/bot deploy comments, base64
    status blobs, HTML comments) so summaries and memories reflect real content."""
    if not text:
        return ""
    text = re.sub(r"\[vc\]:\s*#\S+", " ", text)              # vercel status token
    text = re.sub(r"\b[A-Za-z0-9+/]{80,}={0,2}\b", " ", text)  # base64 blobs
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)      # html comments
    text = re.sub(r"\U0001F916 Generated with .*$", "", text, flags=re.S)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def summarize_pr(title: str, body: str, threads: str) -> tuple[str, str]:
    """(understanding, remember) — falls back to the title/body if the LLM is
    unavailable or the breaker is open, so a PR comment always posts."""
    clean_body = strip_bot_noise(body)
    clean_threads = strip_bot_noise(threads)
    fallback = (
        (clean_body.split("\n", 1)[0][:240] or title).strip(),
        f"{title}".strip()[:200],
    )
    if settings.mode != "live":
        return fallback

    context = f"Title: {title}\n\nDescription:\n{clean_body or '(none)'}"
    if clean_threads:
        context += f"\n\nReview discussion:\n{clean_threads[:2000]}"
    prompt = (
        "You are Lore, an engineering team's decision memory, reacting to a pull "
        "request that was just opened. Read it and respond in EXACTLY this format, "
        "nothing else:\n"
        "UNDERSTOOD: <2-3 sentences: what this PR changes and, if stated, WHY. "
        "Be concrete and technical. Do not invent anything not in the text.>\n"
        "REMEMBER: <one line: the key decision/rationale you'll store in the Canon.>\n\n"
        f"{context}\n"
    )
    try:
        out = _groq_breaker.call(lambda: _call_groq(prompt))
    except (CircuitOpenError, Exception):
        return fallback

    understood, remember = fallback
    m1 = re.search(r"UNDERSTOOD:\s*(.+?)(?:\nREMEMBER:|\Z)", out, re.S)
    m2 = re.search(r"REMEMBER:\s*(.+)\Z", out, re.S)
    if m1:
        understood = m1.group(1).strip()
    if m2:
        remember = m2.group(1).strip()
    return understood, remember


def _call_groq(prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    return client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    ).choices[0].message.content.strip()


def pr_understanding_comment(title: str, body: str, threads: str) -> str:
    understood, remember = summarize_pr(title, body, threads)
    return (
        "## \U0001F9E0 Lore\n\n"
        "**What I understood from this PR**\n\n"
        f"{understood}\n\n"
        "**What I'll remember**\n\n"
        f"> {remember}\n\n"
        "_I inscribe this into the Canon when the PR merges — then anyone can ask "
        "why it was done via `npx lore recall \"…\"` or the Lore editor extension._"
    )


def welcome_body(account: str, repos: list[str], backfill_days: int) -> str:
    repo_list = ", ".join(f"`{r}`" for r in repos[:8])
    more = "" if len(repos) <= 8 else f" (+{len(repos) - 8} more)"
    return (
        "## \U0001F9E0 Lore is now active\n\n"
        "Thanks for installing **Lore** — your team's engineering decision memory.\n\n"
        f"I'm indexing the **last {backfill_days} days** of pull requests "
        f"(titles, descriptions **and** review discussion) across the selected "
        f"repositories for **{account}**:\n\n> {repo_list}{more}\n\n"
        "Once indexing finishes, ask me *why* anything was built the way it is — "
        "in your editor via the Lore extension or `npx lore recall \"...\"` — and "
        "I'll answer from the real decisions across **all** these repos, with "
        "citations back to the PRs.\n\n"
        "_No action needed. This comment is a one-time hello._"
    )
