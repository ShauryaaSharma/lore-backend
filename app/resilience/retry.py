"""Retry with exponential backoff + full jitter.

Without jitter, retries from many callers synchronize and create a
thundering herd against the downstream (GitHub/Groq) right as it's
recovering. This is the AWS-architecture-blog "full jitter" formula:
sleep = random(0, base * 2**attempt), capped.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger("lore.resilience")

T = TypeVar("T")

# Exceptions worth retrying: network hiccups and 5xx/429 from `requests`.
# Import lazily inside the functions that need it to keep this module
# dependency-free for pure unit tests.


def retry(
    max_attempts: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 20.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    should_retry_response: Callable[[object], bool] | None = None,
):
    """Decorator: retry the wrapped call up to `max_attempts` times.

    `should_retry_response`, if given, is called with the function's return
    value; returning True triggers a retry even without an exception (e.g. an
    HTTP response object with status_code in (429, 500, 502, 503, 504)).
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    result = fn(*args, **kwargs)
                except retry_on as exc:  # noqa: PERF203 - intentional broad retry boundary
                    last_exc = exc
                    result = None
                else:
                    if should_retry_response is None or not should_retry_response(result):
                        return result
                    last_exc = None

                if attempt == max_attempts - 1:
                    if last_exc is not None:
                        raise last_exc
                    return result  # give up, return the last (bad) response

                delay = min(max_delay, base_delay * (2**attempt))
                sleep_for = random.uniform(0, delay)
                logger.warning(
                    "retrying %s (attempt %d/%d) after %.2fs",
                    fn.__qualname__, attempt + 1, max_attempts, sleep_for,
                )
                time.sleep(sleep_for)
            raise RuntimeError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
