#!/usr/bin/env python3
"""Reusable resilience patterns for OpenAI and Groq HTTP integrations."""

from __future__ import annotations

import argparse
import logging
import re
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
SUPPORTED_PROVIDERS = {"openai", "groq"}


class LLMHTTPError(RuntimeError):
    """Base error carrying provider and HTTP metadata for retry policies."""

    def __init__(
        self,
        message: str,
        *,
        provider: Optional[str] = None,
        status_code: int,
        headers: Optional[Mapping[str, str]] = None,
        error_code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.error_code = error_code


class LLMBadRequestError(LLMHTTPError):
    """Use for 400 errors so the circuit breaker can ignore them."""


class LLMAuthError(LLMHTTPError):
    """Use for 401 errors so the circuit breaker can ignore them."""


class LLMRetryableError(LLMHTTPError):
    """Use for retryable provider throttling and transient server failures."""


@dataclass(frozen=True)
class DemoResponse:
    headers: Mapping[str, str]


@dataclass(frozen=True)
class OpenAIRateLimitState:
    request_limit: Optional[int]
    token_limit: Optional[int]
    request_remaining: Optional[int]
    token_remaining: Optional[int]
    request_reset_seconds: Optional[float]
    token_reset_seconds: Optional[float]


@dataclass(frozen=True)
class GroqRateLimitState:
    requests_per_day_limit: Optional[int]
    tokens_per_minute_limit: Optional[int]
    requests_per_day_remaining: Optional[int]
    tokens_per_minute_remaining: Optional[int]
    requests_per_day_reset_seconds: Optional[float]
    tokens_per_minute_reset_seconds: Optional[float]


def parse_int_header(value: Optional[str]) -> Optional[int]:
    """Parse an integer header when present."""
    if value is None:
        return None

    raw_value = value.strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError:
        return None


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


def parse_rate_limit_duration_seconds(value: Optional[str]) -> Optional[float]:
    """Parse provider reset durations such as 1s, 6m0s, or 2m59.56s."""
    if value is None:
        return None

    raw_value = value.strip()
    if not raw_value:
        return None

    pattern = re.compile(
        r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
        r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
        r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
    )
    match = pattern.fullmatch(raw_value)
    if match is None:
        return None

    hours = float(match.group("hours") or 0.0)
    minutes = float(match.group("minutes") or 0.0)
    seconds = float(match.group("seconds") or 0.0)

    if hours == 0.0 and minutes == 0.0 and seconds == 0.0:
        return None

    return hours * 3600 + minutes * 60 + seconds


def extract_retry_after_seconds(response: Any) -> Optional[float]:
    """Read response.headers.get('Retry-After') and normalize it."""
    retry_after_value = response.headers.get("Retry-After") or response.headers.get(
        "retry-after"
    )
    return parse_retry_after_seconds(retry_after_value)


def extract_openai_rate_limit_state(headers: Mapping[str, str]) -> OpenAIRateLimitState:
    """Extract OpenAI rate-limit state from response headers."""
    return OpenAIRateLimitState(
        request_limit=parse_int_header(headers.get("x-ratelimit-limit-requests")),
        token_limit=parse_int_header(headers.get("x-ratelimit-limit-tokens")),
        request_remaining=parse_int_header(headers.get("x-ratelimit-remaining-requests")),
        token_remaining=parse_int_header(headers.get("x-ratelimit-remaining-tokens")),
        request_reset_seconds=parse_rate_limit_duration_seconds(
            headers.get("x-ratelimit-reset-requests")
        ),
        token_reset_seconds=parse_rate_limit_duration_seconds(
            headers.get("x-ratelimit-reset-tokens")
        ),
    )


def extract_groq_rate_limit_state(headers: Mapping[str, str]) -> GroqRateLimitState:
    """Extract Groq rate-limit state using Groq-specific header meanings."""
    return GroqRateLimitState(
        requests_per_day_limit=parse_int_header(headers.get("x-ratelimit-limit-requests")),
        tokens_per_minute_limit=parse_int_header(headers.get("x-ratelimit-limit-tokens")),
        requests_per_day_remaining=parse_int_header(
            headers.get("x-ratelimit-remaining-requests")
        ),
        tokens_per_minute_remaining=parse_int_header(
            headers.get("x-ratelimit-remaining-tokens")
        ),
        requests_per_day_reset_seconds=parse_rate_limit_duration_seconds(
            headers.get("x-ratelimit-reset-requests")
        ),
        tokens_per_minute_reset_seconds=parse_rate_limit_duration_seconds(
            headers.get("x-ratelimit-reset-tokens")
        ),
    )


def compute_openai_backpressure_delay(headers: Mapping[str, str]) -> Optional[float]:
    """Choose the binding OpenAI reset delay when a bucket is exhausted."""
    rate_limit_state = extract_openai_rate_limit_state(headers)
    candidate_delays = []

    if (
        rate_limit_state.request_remaining == 0
        and rate_limit_state.request_reset_seconds is not None
    ):
        candidate_delays.append(rate_limit_state.request_reset_seconds)

    if (
        rate_limit_state.token_remaining == 0
        and rate_limit_state.token_reset_seconds is not None
    ):
        candidate_delays.append(rate_limit_state.token_reset_seconds)

    if not candidate_delays:
        return None

    return max(candidate_delays)


def compute_groq_backpressure_delay(headers: Mapping[str, str]) -> Optional[float]:
    """Choose the binding Groq reset delay when RPD or TPM is exhausted."""
    rate_limit_state = extract_groq_rate_limit_state(headers)
    candidate_delays = []

    if (
        rate_limit_state.requests_per_day_remaining == 0
        and rate_limit_state.requests_per_day_reset_seconds is not None
    ):
        candidate_delays.append(rate_limit_state.requests_per_day_reset_seconds)

    if (
        rate_limit_state.tokens_per_minute_remaining == 0
        and rate_limit_state.tokens_per_minute_reset_seconds is not None
    ):
        candidate_delays.append(rate_limit_state.tokens_per_minute_reset_seconds)

    if not candidate_delays:
        return None

    return max(candidate_delays)


def compute_provider_backpressure_delay(
    provider: Optional[str], headers: Mapping[str, str]
) -> Optional[float]:
    """Dispatch to provider-specific backpressure calculation."""
    if provider == "openai":
        return compute_openai_backpressure_delay(headers)

    if provider == "groq":
        return compute_groq_backpressure_delay(headers)

    return None


def is_retryable_llm_error(error: BaseException) -> bool:
    """Retry throttling, transient server failures, and Groq flex capacity spikes."""
    if not isinstance(error, LLMHTTPError):
        return False

    if error.error_code in {"insufficient_quota", "billing_hard_limit_reached"}:
        return False

    if error.provider == "groq" and (
        error.status_code == 498 or error.error_code == "capacity_exceeded"
    ):
        return True

    if error.status_code in {429, 503}:
        return True

    return 500 <= error.status_code < 600


if wait_exponential_jitter is not None:
    _jitter_wait = wait_exponential_jitter(initial=1, max=60)
else:  # pragma: no cover - exercised only without tenacity installed
    _jitter_wait = None


def wait_for_retry_after_or_jitter(retry_state: Any) -> float:
    """Honor Retry-After first, then provider resets, then exponential jitter."""
    error = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(error, LLMHTTPError):
        retry_after_seconds = parse_retry_after_seconds(
            error.headers.get("Retry-After") or error.headers.get("retry-after")
        )
        if retry_after_seconds is not None:
            return retry_after_seconds

        provider_backpressure_delay = compute_provider_backpressure_delay(
            error.provider,
            error.headers,
        )
        if provider_backpressure_delay is not None:
            return provider_backpressure_delay

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
    def send_with_retry(
        request_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Wrap the provider call in header-aware retry logic."""
        return request_fn(*args, **kwargs)

else:  # pragma: no cover - exercised only without tenacity installed

    def send_with_retry(
        request_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
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
    """Demonstrate a retryable OpenAI rate-limit failure."""
    raise LLMRetryableError(
        "provider throttled request",
        provider="openai",
        status_code=429,
        headers={"Retry-After": "3"},
    )


def demo_retry_after() -> Optional[float]:
    """Demonstrate explicit Retry-After extraction from response headers."""
    response = DemoResponse(headers={"Retry-After": "7"})
    retry_after_seconds = extract_retry_after_seconds(response)
    print(f"Retry-After delay: {retry_after_seconds}")
    return retry_after_seconds


def demo_openai_headers() -> OpenAIRateLimitState:
    """Demonstrate OpenAI rate-limit header parsing."""
    headers = {
        "x-ratelimit-limit-requests": "60",
        "x-ratelimit-limit-tokens": "150000",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-remaining-tokens": "149984",
        "x-ratelimit-reset-requests": "1s",
        "x-ratelimit-reset-tokens": "6m0s",
    }
    rate_limit_state = extract_openai_rate_limit_state(headers)
    binding_delay = compute_openai_backpressure_delay(headers)
    print(f"OpenAI request remaining: {rate_limit_state.request_remaining}")
    print(f"OpenAI token remaining: {rate_limit_state.token_remaining}")
    print(f"OpenAI binding delay: {binding_delay}")
    return rate_limit_state


def demo_groq_headers() -> GroqRateLimitState:
    """Demonstrate Groq rate-limit header parsing."""
    headers = {
        "x-ratelimit-limit-requests": "14400",
        "x-ratelimit-limit-tokens": "18000",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-remaining-tokens": "17997",
        "x-ratelimit-reset-requests": "2m59.56s",
        "x-ratelimit-reset-tokens": "7.66s",
        "retry-after": "8",
    }
    rate_limit_state = extract_groq_rate_limit_state(headers)
    binding_delay = compute_groq_backpressure_delay(headers)
    retry_after_seconds = parse_retry_after_seconds(headers.get("retry-after"))
    print(f"Groq RPD remaining: {rate_limit_state.requests_per_day_remaining}")
    print(f"Groq TPM remaining: {rate_limit_state.tokens_per_minute_remaining}")
    print(f"Groq binding delay: {binding_delay}")
    print(f"Groq retry-after: {retry_after_seconds}")
    return rate_limit_state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run lightweight demos for the resilience template."
    )
    parser.add_argument(
        "--demo-retry-after",
        action="store_true",
        help="Print the parsed Retry-After delay from a demo response.",
    )
    parser.add_argument(
        "--demo-openai-headers",
        action="store_true",
        help="Print parsed OpenAI rate-limit headers and binding delay.",
    )
    parser.add_argument(
        "--demo-groq-headers",
        action="store_true",
        help="Print parsed Groq rate-limit headers and binding delay.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.demo_retry_after:
        demo_retry_after()
        return 0

    if args.demo_openai_headers:
        demo_openai_headers()
        return 0

    if args.demo_groq_headers:
        demo_groq_headers()
        return 0

    print("Supported providers:")
    for provider in sorted(SUPPORTED_PROVIDERS):
        print(f"  - {provider}")
    print("Run with --demo-retry-after, --demo-openai-headers, or --demo-groq-headers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
