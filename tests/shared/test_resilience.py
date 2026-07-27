"""Tests for research_shared.resilience — retry, circuit breaker, backoff."""


import pytest

from research_shared.resilience import (
    CircuitBreaker,
    CircuitState,
    ResilienceError,
    RetryConfig,
    retry,
)


class TestRetryConfig:
    def test_defaults(self):
        """RetryConfig has sensible defaults."""
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 0.5
        assert cfg.max_delay == 30.0
        assert cfg.exponential_base == 2.0

    def test_custom_values(self):
        """All fields accept custom values."""
        cfg = RetryConfig(
            max_retries=5, base_delay=1.0, max_delay=10.0, exponential_base=3.0
        )
        assert cfg.max_retries == 5
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 10.0
        assert cfg.exponential_base == 3.0

    def test_delay_for_attempt(self):
        """delay_for_attempt calculates exponential backoff."""
        cfg = RetryConfig(base_delay=1.0, exponential_base=2.0, max_delay=100.0)
        assert cfg.delay_for_attempt(0) == 1.0
        assert cfg.delay_for_attempt(1) == 2.0
        assert cfg.delay_for_attempt(2) == 4.0
        assert cfg.delay_for_attempt(3) == 8.0

    def test_delay_capped_at_max(self):
        """delay_for_attempt never exceeds max_delay."""
        cfg = RetryConfig(base_delay=10.0, exponential_base=10.0, max_delay=30.0)
        # attempt 0: 10, attempt 1: 100 → capped at 30
        assert cfg.delay_for_attempt(0) == 10.0
        assert cfg.delay_for_attempt(1) == 30.0


class TestResilienceError:
    def test_is_exception(self):
        """ResilienceError is a proper exception."""
        err = ResilienceError("Max retries exceeded")
        assert str(err) == "Max retries exceeded"
        assert isinstance(err, Exception)


class TestCircuitBreaker:
    def test_starts_closed(self):
        """Circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_record_failure(self):
        """Recording failures increments the counter."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.failure_count == 1
        cb.record_failure()
        assert cb.failure_count == 2

    def test_trips_to_open(self):
        """When failures reach threshold, circuit opens."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_success_resets_counter(self):
        """A success resets the failure counter."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0

    def test_allows_when_closed(self):
        """Circuit allows execution when CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        assert cb.allows() is True

    def test_rejects_when_open(self):
        """Circuit rejects execution when OPEN."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=60.0
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allows() is False

    def test_transitions_to_half_open(self, monkeypatch):
        """After recovery_timeout, circuit goes HALF_OPEN."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.1
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Fast-forward past recovery timeout
        import time

        original = time.monotonic
        fast_forward = original() + 1.0
        monkeypatch.setattr(time, "monotonic", lambda: fast_forward)

        # Next call triggers half-open check
        assert cb.allows() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        """Success in HALF_OPEN resets to CLOSED."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
        cb.record_failure()  # OPEN
        cb.state = CircuitState.HALF_OPEN  # simulate timeout
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        """Failure in HALF_OPEN goes back to OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        """retry returns result on first success."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.001)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """retry retries after transient failures then succeeds."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.001)
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = await fail_twice()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        """retry raises ResilienceError when all retries exhausted."""
        call_count = 0

        @retry(max_retries=2, base_delay=0.001)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("persistent")

        with pytest.raises(ResilienceError, match="Max retries"):
            await always_fail()
        # 1 initial + 2 retries = 3 calls
        assert call_count == 3
