# OpenAI Rate Limits

Read this file when the target integration uses the OpenAI API.

## What Must Drive Pacing

- Treat OpenAI limits as multi-dimensional: RPM, RPD, TPM, TPD, and IPM.
- Treat OpenAI limits as organization-level and project-level, not user-level.
- Treat limits as model-specific.
- Treat some model families as shared-limit groups when the limits page says they share a bucket.
- Treat long-context requests as a separate bucket when the limits page exposes one.
- Treat Batch API queue limits as queued input-token limits for the model.

## What Tier Means

- A usage tier tells you the spend qualification and monthly usage cap.
- A tier does not tell you the exact per-model operational limit you should pace against.
- If the user says "I am on Tier 1", use that as budget context only.
- For exact pacing, prefer one of these inputs:
  1. Actual response headers from the target workload.
  2. The authenticated limits page at `https://platform.openai.com/settings/organization/limits`.
  3. Explicit per-model numbers provided by the user.

## Headers To Parse

Parse these headers when present:

- `x-ratelimit-limit-requests`
- `x-ratelimit-limit-tokens`
- `x-ratelimit-remaining-requests`
- `x-ratelimit-remaining-tokens`
- `x-ratelimit-reset-requests`
- `x-ratelimit-reset-tokens`
- `Retry-After`

Use `Retry-After` first for explicit retry timing. Use the reset headers to update local limiter state and to choose which budget dimension is currently binding.

## OpenAI-Specific Retry Rules

- Retry rate-limit `429` responses with header-aware backoff.
- Do not blindly retry quota-exhaustion `429` responses such as monthly budget or prepaid-credit exhaustion.
- Retry transient `500` and `503` responses with backoff.
- If OpenAI returns `503 Slow Down`, reduce the request rate, hold it steady for at least 15 minutes, then ramp up gradually.
- Remember that failed requests still count against per-minute limits.

## Throughput Optimization

- Set `max_tokens` close to the realistic output size because the limit calculation can be driven by that configured ceiling.
- If RPM is the bottleneck and TPM still has headroom, batch work where the API shape supports it.
- If the workload is asynchronous, consider the Batch API so synchronous request limits are not the main constraint.
