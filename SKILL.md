---
name: applying-resilience-patterns
description: "Trigger this skill when the user asks to /rate-limit, apply rate limiting, throttling, backoff, or resilience to LLM API usage. Instructs the agent on how to deterministically implement exponential backoff with jitter, circuit breakers, header parsing, semantic caching, and orchestration concurrency controls."
---

# Applying Resilience Patterns

Implement resilient LLM integrations with deterministic retry, throttling, and concurrency controls. Read `scripts/resilience_templates.py` before editing Python retry or breaker code, then adapt that template to the target project instead of writing custom control flow from scratch. When the provider is OpenAI, also read `references/openai-rate-limits.md` before choosing quotas, retry behavior, or pacing assumptions.

## Workflow

1. Inspect the codebase to find the single boundary where LLM calls leave the application. Prefer modifying one shared gateway, client wrapper, or service module over scattering retries across call sites.
2. Analyze the target project source code to identify the specific LLM provider in use (for example OpenAI, Anthropic, Gemini, Groq, DeepSeek, Azure OpenAI) to anticipate provider-specific headers, quota models, and error codes.
3. If the provider is OpenAI, do not guess limits from memory. Read `references/openai-rate-limits.md`, inspect actual response headers, and prefer the authenticated limits page when the user can access it.
4. Treat a user statement such as "I am on Tier 1" as helpful but insufficient. Tier identifies spend qualification and monthly budget, not the exact per-model RPM, TPM, long-context, shared-family, or project-level limit that should drive pacing.
5. Reuse existing abstractions, logging, configuration, and test helpers already present in the project. Preserve the project style instead of introducing a parallel client stack.
6. Read `scripts/resilience_templates.py` and adapt its retry, `Retry-After`, and circuit-breaker patterns to the project's HTTP client and exception model.
7. Add or update regression coverage around the shared LLM boundary when the project has tests. Validate both happy-path behavior and throttling behavior.

## Reactive Handling

Implement Reactive Header-Driven Handling. Use the `tenacity` library in Python to wrap all LLM network calls.

1. Write logic to always parse the `Retry-After` header first.
2. If the header is present, wait exactly that long before the next retry attempt.
3. If the header is missing, implement Exponential Backoff with Jitter with base `1s` and max `60s` to mathematically prevent thundering herd issues.
4. Explicitly handle HTTP `429` and `503` errors.
5. Treat transient `5xx`, timeout, and connection-reset errors as retry candidates only when the surrounding call is idempotent or safe to repeat.
6. Avoid retrying deterministic client errors such as malformed requests.
7. Emit structured logs that include provider, model, status code, retry attempt, and computed delay.
8. For OpenAI, parse `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, and `x-ratelimit-reset-tokens` when present, and pace against the most constrained dimension.
9. For OpenAI, distinguish retryable `429` rate-limit responses from non-retryable `429` quota or billing exhaustion responses.

## Circuit Breaker

Implement the Circuit Breaker Pattern. Use the `pybreaker` library to open the circuit after `5` consecutive `429` or `500`-level errors, instantly preventing infinite hangs on high-latency LLM calls.

1. Exclude `400` and `401` client errors from tripping the breaker.
2. Reset the breaker only after a cool-down window that fits the latency profile of the target model.
3. Keep the breaker at the same shared LLM boundary as the retry logic.
4. Raise or map a project-specific fail-fast exception when the breaker is open so upstream code can degrade gracefully.

## Proactive Throttling

Implement Proactive Throttling.

1. Set up a local client-side token bucket rate limiter that tracks estimated input and output tokens per minute.
2. Keep effective throughput `10%` under the provider's known threshold to preserve headroom for jitter, clock skew, and concurrent workers.
3. Queue, delay, or reject locally when insufficient request or token budget is available instead of letting the provider reject the call.
4. Prefer shared state such as Redis only when the application has multiple workers or hosts that must coordinate the same budget.
5. Keep the limiter configuration provider-aware and model-aware when the codebase already separates those concepts.
6. For OpenAI, treat limits as organization-level and project-level constraints, not user-level constraints.
7. For OpenAI, scope pacing by model family and shared-limit groups instead of assuming every model has an independent budget.
8. For OpenAI, account for long-context request limits separately when the target model uses a distinct long-context bucket.
9. For OpenAI, remember that failed retries still count against per-minute limits.

## Framework Optimizations

Implement Framework Optimizations when orchestration layers are present.

1. Enforce explicit `max_concurrency` or equivalent fan-out limits on every parallel LLM execution path to prevent network spikes.
2. Inspect async helpers, worker pools, graph runners, and evaluation harnesses for hidden parallel LLM calls.
3. Trim or bound unbounded chat history if the integration keeps appending old context into every call and rapidly burns token budgets.

## Caching Guidance

Recommend Semantic Caching.

1. Prompt the user in the console to integrate a Redis-backed semantic cache or GPTCache to bypass API limits entirely for semantically similar queries.
2. Frame caching as a direct rate-limit multiplier, not only a latency optimization.
3. Suggest cache insertion only for prompts whose outputs are stable enough to reuse.
4. For OpenAI, also recommend reducing `max_tokens` to the closest realistic output size and batching synchronous workloads only when RPM is saturated and TPM headroom remains.

## Implementation Rules

1. Prefer battle-tested libraries over custom retry loops or breaker implementations.
2. Keep deterministic code paths low freedom. Do not invent new backoff formulas when the template already fits.
3. Use Unix-style forward slashes in every file path you write or reference.
4. Keep changes concentrated, legible, and easy for the next agent to extend.
5. When the provider is OpenAI, never hardcode tier assumptions as exact operational limits. Use actual headers, the authenticated limits page, or explicit user-provided numbers for the target model.
