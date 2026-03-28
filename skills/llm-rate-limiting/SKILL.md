---
name: llm-rate-limiting
description: "Trigger this skill when the user asks to /rate-limit, pace provider requests, handle quota headers, usage tiers, or resilient retries for LLM APIs such as OpenAI or Groq. Use for LLM/provider API limits and quota handling, not generic CDN, nginx, or web-app throttling. Instructs the agent to implement deterministic backoff, circuit breakers, provider-specific header parsing, semantic caching, and concurrency controls."
metadata:
  author: Talha Sari
  version: 1.2.0
  providers:
    - openai
    - groq
---

# LLM Rate Limiting

Implement resilient LLM integrations with deterministic retry, throttling, quota handling, and concurrency controls. Read `references/examples.md` to understand expected triggers and non-triggers. Read `references/troubleshooting.md` when symptoms do not match the happy path.

## Workflow

1. Inspect the codebase to find the single boundary where LLM calls leave the application. Prefer modifying one shared gateway, client wrapper, or service module over scattering retries across call sites.
2. Analyze the target project source code to identify the specific LLM provider in use. Treat OpenAI and Groq as first-class branches with provider-specific header semantics and limit models.
3. If the provider is OpenAI, read `references/openai-rate-limits.md` before choosing quotas, retry behavior, or pacing assumptions.
4. If the provider is Groq, read `references/groq-rate-limits.md` before choosing quotas, retry behavior, or pacing assumptions.
5. If the user says "I am on Tier 1" or provides another plan label, treat it as budget context only unless the provider docs say it fully determines operational limits.
6. Reuse existing abstractions, logging, configuration, and test helpers already present in the project. Preserve the project style instead of introducing a parallel client stack.
7. Read `scripts/resilience_templates.py` and adapt its retry, reset-window, and circuit-breaker patterns to the project's HTTP client and exception model.
8. Add or update regression coverage around the shared LLM boundary when the project has tests. Validate happy paths, throttling paths, and provider-specific header parsing.

## Reactive Handling

Implement Reactive Header-Driven Handling. Use the `tenacity` library in Python to wrap all LLM network calls.

1. Parse `Retry-After` first when it is present.
2. If `Retry-After` is missing, pace using the provider's reset headers before falling back to exponential backoff with jitter.
3. Keep exponential jitter in the `1s` to `60s` range to avoid thundering herd spikes.
4. Explicitly handle HTTP `429` and `503` errors.
5. Treat transient `5xx`, timeout, and connection-reset errors as retry candidates only when the surrounding call is idempotent or safe to repeat.
6. Avoid retrying deterministic client errors such as malformed requests.
7. Emit structured logs that include provider, model, status code, retry attempt, and computed delay.
8. For OpenAI, parse `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, and `x-ratelimit-reset-tokens`, and pace against the most constrained dimension.
9. For Groq, parse `retry-after` plus `x-ratelimit-*` headers, remembering that request headers refer to RPD and token headers refer to TPM.
10. Distinguish retryable throttling from non-retryable quota or billing exhaustion.

## Circuit Breaker

Implement the Circuit Breaker Pattern. Use the `pybreaker` library to open the circuit after `5` consecutive throttling or transient server failures.

1. Exclude `400` and `401` client errors from tripping the breaker.
2. Keep the breaker at the same shared LLM boundary as the retry logic.
3. Raise or map a project-specific fail-fast exception when the breaker is open so upstream code can degrade gracefully.
4. For Groq flex processing, treat status `498` with `capacity_exceeded` as a retryable capacity signal, not as a permanent application error.

## Proactive Throttling

Implement Proactive Throttling.

1. Set up a local client-side token bucket or equivalent limiter that tracks the provider dimensions actually exposed by the target API.
2. Keep effective throughput about `10%` under known thresholds to preserve headroom for jitter, clock skew, and concurrent workers.
3. Queue, delay, or reject locally when insufficient request or token budget is available instead of letting the provider reject the call.
4. Prefer shared state such as Redis only when the application has multiple workers or hosts that must coordinate the same budget.
5. For OpenAI, treat limits as organization-level and project-level constraints, not user-level constraints.
6. For OpenAI, scope pacing by model family and shared-limit groups instead of assuming every model has an independent budget.
7. For OpenAI, account for long-context request limits separately when the target model uses a distinct long-context bucket.
8. For Groq, treat limits as organization-level constraints and remember that project-level custom limits can only be more restrictive than the org ceiling.
9. For Groq, remember that cached tokens do not count toward rate limits, but parallel traffic can still exhaust non-cached capacity.

## Framework Optimizations

Implement Framework Optimizations when orchestration layers are present.

1. Enforce explicit `max_concurrency` or equivalent fan-out limits on every parallel LLM execution path to prevent network spikes.
2. Inspect async helpers, worker pools, graph runners, and evaluation harnesses for hidden parallel LLM calls.
3. Trim or bound unbounded chat history if the integration keeps appending old context into every call and rapidly burns token budgets.

## Caching Guidance

Recommend Semantic Caching and provider-aware throughput tuning.

1. Prompt the user in the console to integrate a Redis-backed semantic cache or GPTCache to bypass repeated external calls.
2. Frame caching as a direct rate-limit multiplier, not only a latency optimization.
3. Suggest cache insertion only for prompts whose outputs are stable enough to reuse.
4. For OpenAI, recommend reducing `max_tokens` to the closest realistic output size and batching synchronous workloads only when RPM is saturated and TPM headroom remains.
5. For Groq, recommend prompt caching when the model supports it and the workload reuses large shared prefixes.

## Implementation Rules

1. Prefer battle-tested libraries over custom retry loops or breaker implementations.
2. Keep deterministic code paths low freedom. Do not invent new backoff formulas when the template already fits.
3. Use Unix-style forward slashes in every file path you write or reference.
4. Keep provider semantics explicit. Do not assume one provider's header meanings apply to another.
5. Use actual headers, authenticated limits pages, or explicit user-provided numbers when exact pacing matters.
6. Keep the skill folder clean: no `README.md`, no repo-only docs, and no screenshots inside the installable skill.
