"""resilience.py — retry, circuit breaker, and exponential backoff.

Provides infrastructure-level resilience patterns shared by all MCPs:
- RetryConfig / retry() decorator for transient-error handling
- CircuitBreaker for fail-fast behaviour when downstream is unhealthy
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# ResilienceError
# ---------------------------------------------------------------------------

class ResilienceError(Exception):
    """Raised when a resilience pattern exhausts its attempts."""


# ---------------------------------------------------------------------------
# CircuitState
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    """States for the circuit breaker state machine."""

    CLOSED = auto()  # normal operation — requests flow through
    OPEN = auto()  # failing — requests are rejected immediately
    HALF_OPEN = auto()  # probing — a single trial request is allowed


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Configuration for the retry decorator."""

    max_retries: int = 3
    base_delay: float = 0.5  # seconds
    max_delay: float = 30.0  # seconds
    exponential_base: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate the delay before a retry attempt.

        Uses exponential backoff: base_delay * (exponential_base ** attempt),
        capped at max_delay.
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


# ---------------------------------------------------------------------------
# retry decorator
# ---------------------------------------------------------------------------

def retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
) -> Callable[[F], F]:
    """Decorator: retry an async function with exponential backoff.

    Raises ResilienceError when all retries are exhausted.
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (OSError, TimeoutError, ConnectionError) as exc:
                    last_exception = exc
                    if attempt < config.max_retries:
                        delay = config.delay_for_attempt(attempt)
                        await asyncio.sleep(delay)
            raise ResilienceError(
                f"Max retries ({config.max_retries}) exceeded. "
                f"Last error: {last_exception}"
            ) from last_exception

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """A simple circuit breaker that trips after *failure_threshold*
    consecutive failures.

    State machine:
        CLOSED → (failures >= threshold) → OPEN
        OPEN → (recovery_timeout elapsed) → HALF_OPEN
        HALF_OPEN → (success) → CLOSED
        HALF_OPEN → (failure) → OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.state: CircuitState = CircuitState.CLOSED
        self._last_failure_time: float = 0.0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def allows(self) -> bool:
        """Return True if the circuit allows a request through."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self._recovery_timeout_elapsed():
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow a single probe
        return True

    def record_success(self) -> None:
        """Notify the breaker of a successful call."""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Notify the breaker of a failed call."""
        self.failure_count += 1
        self._last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN or (
            self.state == CircuitState.CLOSED
            and self.failure_count >= self.failure_threshold
        ):
            self.state = CircuitState.OPEN

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _recovery_timeout_elapsed(self) -> bool:
        return (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
