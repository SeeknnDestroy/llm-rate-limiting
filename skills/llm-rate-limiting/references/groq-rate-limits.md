# Groq Rate Limits

Read this file when the target integration uses the Groq API.

## What Must Drive Pacing

- Treat Groq limits as multi-dimensional: RPM, RPD, TPM, TPD, ASH, and ASD.
- Treat Groq limits as organization-level, not user-level.
- Treat the limits page as the exact source of truth for the current account.
- Treat project-level custom limits as more restrictive overlays, not higher ceilings.

## Header Semantics

Parse these headers when present:

- `retry-after`
- `x-ratelimit-limit-requests`
- `x-ratelimit-limit-tokens`
- `x-ratelimit-remaining-requests`
- `x-ratelimit-remaining-tokens`
- `x-ratelimit-reset-requests`
- `x-ratelimit-reset-tokens`

Use Groq semantics, not OpenAI semantics:

- `x-ratelimit-limit-requests` refers to Requests Per Day (RPD)
- `x-ratelimit-limit-tokens` refers to Tokens Per Minute (TPM)
- `x-ratelimit-reset-requests` refers to the RPD reset window
- `x-ratelimit-reset-tokens` refers to the TPM reset window
- `retry-after` is only set when a `429` rate-limit response is returned
- reset values can be fractional strings such as `2m59.56s` or `7.66s`

## Service Tiers and Batch

- Groq service tiers affect behavior and throughput.
- Flex processing provides higher rate limits for paid customers but can fail fast when capacity is unavailable.
- Treat status `498` with error `capacity_exceeded` as a retryable flex-capacity signal.
- Add jittered backoff around flex spikes.
- Batch has its own processing window and rate limits.
- Batch does not accept the `service_tier` parameter.

## Throughput Optimization

- Cached tokens do not count toward rate limits.
- Prompt caching still does not guarantee that large parallel workloads will avoid limits, so keep concurrency bounded.
- If the workload is asynchronous, consider Groq Batch instead of consuming synchronous limits.

## Practical Rules

- Do not assume OpenAI-style org/project/model buckets or tier naming.
- Do not assume the same `x-ratelimit-*` header names mean the same quota dimensions across providers.
- Prefer the account limits page over hardcoded tables when exact numbers matter.
