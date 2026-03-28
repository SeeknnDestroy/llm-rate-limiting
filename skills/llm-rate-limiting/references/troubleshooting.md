# Troubleshooting

## OpenAI tier info is provided but exact limits are missing

Cause:
The user provided a tier label, not the exact model-level operational limits.

Fix:
Use the authenticated OpenAI limits page, actual response headers, or explicit per-model numbers before finalizing pacing.

## OpenAI 429 keeps retrying but should stop

Cause:
The implementation is treating quota or billing exhaustion like a transient rate-limit event.

Fix:
Differentiate retryable rate-limit throttling from non-retryable quota exhaustion such as `insufficient_quota`.

## Groq reset parsing is wrong

Cause:
The implementation assumed integer-only reset windows and failed on values like `2m59.56s`.

Fix:
Use a duration parser that supports fractional seconds in the `h`, `m`, and `s` segments.

## Groq client uses OpenAI-compatible API shape but wrong semantics

Cause:
The transport shape looks OpenAI-compatible, so the implementation reused OpenAI header logic.

Fix:
Treat protocol compatibility and quota semantics separately. Reuse request syntax if needed, but keep Groq-specific limit parsing.

## Flex requests fail with 498 capacity_exceeded

Cause:
Flex capacity is temporarily unavailable.

Fix:
Apply jittered retries or fall back to a non-flex tier if the product can tolerate lower throughput.
