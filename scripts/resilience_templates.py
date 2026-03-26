#!/usr/bin/env python3
"""Reusable resilience patterns for LLM HTTP integrations."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Optional

try:
    import pybreaker
except ImportError:  # pragma: no cover - optional dependency for template use
    pybreaker = None

try:
    from tenacity import before_sleep_log
    from tenacity import retry
    from tenacity import retry_if_exception
    from tenacity import stop_after_attempt
    from tenacity import wait_exponential_jitter
except ImportError:  # pragma: no cover - optional dependency for template use
    before_sleep_log = None
    retry = None
    retry_if_exception = None
    stop_after_attempt = None
    wait_exponential_jitter = None

LOGGER = logging.getLogger("llm_resilience")


class LLMHTTPError(RuntimeError):
    """Base error that carries HTTP metadata for retry and breaker policies."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers or {})


class LLMBadRequestError(LLMHTTPError):
    """Use for 400 errors so the circuit breaker can ignore them."""


class LLMAuthError(LLMHTTPError):
    """Use for 401 errors so the circuit breaker can ignore them."""


class LLMRetryableError(LLMHTTPError):
    """Use for 429, 503, and transient 5xx provider responses."""


@dataclass(frozen=True)
class DemoResponse:
    headers: Mapping[str, str]


def parse_retry_after_seconds(retry_after_value: Optional[str]) -> Optional[float]:
    """Parse Retry-After seconds or HTTP-date into a positive delay."""
    if retry_after_value is None:
        return None

    raw_value = retry_after_value.strip()
    if not raw_value:
        return None

    if raw_value.isdigit():
        return max(float(raw_value), 0.0)

    try:
        retry_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delay_seconds = (retry_at - now).total_seconds()
    return max(delay_seconds, 0.0)


def extract_retry_after_seconds(response: Any) -> Optional[float]:
    """Read response.headers.get('Retry-After') and normalize it."""
    retry_after_value = response.headers.get("Retry-After")
    return parse_retry_after_seconds(retry_after_value)


def is_retryable_llm_error(error: BaseException) -> bool:
    """Retry only transient LLM transport and quota failures."""
    if not isinstance(error, LLMHTTPError):
        return False

    if error.status_code in {429, 503}:
        return True

    return 500 <= error.status_code < 600


if wait_exponential_jitter is not None:
    _jitter_wait = wait_exponential_jitter(initial=1, max=60)
else:  # pragma: no cover - exercised only without tenacity installed
    _jitter_wait = None


def wait_for_retry_after_or_jitter(retry_state: Any) -> float:
    """Honor Retry-After first, then fall back to exponential jitter."""
    error = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(error, LLMHTTPError):
        retry_after_seconds = parse_retry_after_seconds(
            error.headers.get("Retry-After")
        )
        if retry_after_seconds is not None:
            return retry_after_seconds

    if _jitter_wait is None:
        raise RuntimeError(
            "Install tenacity to use exponential backoff: pip install tenacity"
        )

    return float(_jitter_wait(retry_state))


if retry is not None:

    @retry(
        retry=retry_if_exception(is_retryable_llm_error),
        wait=wait_for_retry_after_or_jitter,
        stop=stop_after_attempt(6),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    def send_with_retry(request_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Wrap the provider call in header-aware retry logic."""
        return request_fn(*args, **kwargs)

else:  # pragma: no cover - exercised only without tenacity installed

    def send_with_retry(request_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Install tenacity to use send_with_retry().")


if pybreaker is not None:
    llm_circuit_breaker = pybreaker.CircuitBreaker(
        fail_max=5,
        reset_timeout=60,
        exclude=[LLMBadRequestError, LLMAuthError],
    )
else:  # pragma: no cover - exercised only without pybreaker installed
    llm_circuit_breaker = None


def send_with_breaker(request_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run the retried call behind a circuit breaker."""
    if llm_circuit_breaker is None:
        raise RuntimeError("Install pybreaker to use send_with_breaker().")

    return llm_circuit_breaker.call(send_with_retry, request_fn, *args, **kwargs)


def failing_request() -> None:
    """Demonstrate a retryable provider failure."""
    raise LLMRetryableError(
        "provider throttled request",
        status_code=429,
        headers={"Retry-After": "3"},
    )


def demo_retry_after() -> Optional[float]:
    """Demonstrate explicit Retry-After extraction from response headers."""
    response = DemoResponse(headers={"Retry-After": "7"})
    retry_after_seconds = extract_retry_after_seconds(response)
    print(f"Retry-After delay: {retry_after_seconds}")
    return retry_after_seconds


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run lightweight demos for the resilience template."
    )
    parser.add_argument(
        "--demo-retry-after",
        action="store_true",
        help="Print the parsed Retry-After delay from a demo response.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.demo_retry_after:
        demo_retry_after()
        return 0

    print("Dependencies detected:")
    print(f"  tenacity: {'yes' if retry is not None else 'no'}")
    print(f"  pybreaker: {'yes' if pybreaker is not None else 'no'}")
    print("Run with --demo-retry-after to exercise header parsing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
