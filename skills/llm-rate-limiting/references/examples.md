# Examples

Use these examples to judge whether the skill should trigger.

## Should Trigger

- `I'm on Tier 1 for OpenAI. Help me stay under rate limits for gpt-4.1 without guessing from memory.`
- `Use OpenAI headers to pace retries and avoid quota errors in my Python client.`
- `Handle Groq 429s and pace requests using Groq headers and service tiers.`
- `Add jittered retries for Groq flex capacity_exceeded errors.`
- `Implement provider-aware rate limiting and quota handling for my LLM integration.`

## Should Not Trigger

- `Set up nginx rate limiting for my API gateway.`
- `Throttle frontend button clicks with debounce.`
- `Configure Cloudflare WAF rate limits.`
- `Build a generic retry wrapper for REST calls that are not LLM-specific.`

## What Good Behavior Looks Like

- Detect the provider before choosing header semantics.
- Treat OpenAI plan or tier labels as incomplete without exact model limits.
- Treat Groq `x-ratelimit-*` headers using Groq meanings, not OpenAI meanings.
- Keep the logic concentrated at a single shared LLM boundary.
