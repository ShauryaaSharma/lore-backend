import pytest

from app.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.resilience.retry import retry


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @retry(max_attempts=3, base_delay=0.001, max_delay=0.01)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_raises_after_exhausting_attempts():
    @retry(max_attempts=2, base_delay=0.001, max_delay=0.01)
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        always_fails()


def test_retry_on_bad_response_without_exception():
    calls = {"n": 0}

    @retry(max_attempts=3, base_delay=0.001, max_delay=0.01,
          should_retry_response=lambda r: r == "retry-me")
    def sometimes_bad():
        calls["n"] += 1
        return "retry-me" if calls["n"] < 2 else "good"

    assert sometimes_bad() == "good"
    assert calls["n"] == 2


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=100, name="test")

    def boom():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(boom)

    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: "should not run")


def test_circuit_breaker_recovers_after_cooldown():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0, name="test")

    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("down")))

    assert cb.state == CircuitState.HALF_OPEN
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == CircuitState.CLOSED
