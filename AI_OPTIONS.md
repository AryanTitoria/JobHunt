# Hosted AI without an unlimited budget

Checked against official documentation on 18 November 2026. Availability, models, region eligibility and quotas can change; your provider console is authoritative for your account.

| Option | What is available | Boundary |
| --- | --- | --- |
| Gemini API | A free tier for selected models; free input/output tokens within its limits | Quotas depend on the model/project. Free-tier content can be used to improve Google's products. |
| Groq API | A free plan with model-specific rate/token limits for hosted models | It is not unlimited. Requests can be rate limited; check the console's current free-plan limits. |
| OpenAI API | Hosted models billed according to the selected model; any applicable credits are account/program specific | Do not assume a permanent free API allowance. A billing-credit balance is different from a rate limit. |

JobSearch supports all three, using only server-side API keys. The first configured provider is primary. If a user has explicitly enabled fallback, the next configured provider may receive the same redacted resume/job payload when the primary is unavailable. This is ordinary provider failover, not an attempt to bypass a provider's limits. Creating more keys does not necessarily create more quota; Gemini limits apply at the project level, not per key.

## What “out of tokens” can mean

- A per-minute or daily request/token quota: wait until the provider's quota resets or use an eligible paid tier.
- Exhausted prepaid credits or a billing cap: waiting may not replenish paid credits. Review billing and account settings.
- The model's per-request context/output limit: shorten the input or requested output. More API keys do not enlarge a model's context window.

There is no legitimate guarantee of permanently free, unlimited hosted inference. A free tier can be enough for a mentor demonstration, but a real multi-user service needs a predictable budget or explicit limits.

## The approach used in JobSearch

1. Extract resume text and skills locally, without a model call.
2. Collect and share public job data once rather than rediscovering it independently for every user.
3. Use explainable matching to filter and rank the inventory without an LLM call for each job.
4. Use hosted AI only for the selected job's deeper resume review.
5. Cache the review by user, resume version and job content hash.
6. Enforce user/global daily attempt caps, a conservative reserved-token budget and output limits.
7. Honor provider cooldowns, including Retry-After, and avoid automatic retry loops.
8. Keep the platform functional with essential non-AI resume guidance when hosted providers are unavailable.

This fallback is ordinary code-based guidance, not Ollama or another offline model. It prevents the entire product from going down when a quota is reached; it does not replace a detailed model review. Evidence checks reject unsupported quotes and remove proposed wording with unsupported numbers or named skills, but human review is still necessary.

For a student demo, start with one eligible Gemini or Groq free-plan key and a small daily limit. Add another provider only if you need it and users understand where their resume excerpts can go. For real CVs, consider the provider's data-use terms before choosing a free tier. The UI includes consent controls and identifies whether the result came from hosted AI or essential guidance.

Official references:

- Gemini pricing and data-use tiers: https://ai.google.dev/gemini-api/docs/pricing
- Gemini project/model rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Groq free-plan and model-specific limits: https://console.groq.com/docs/rate-limits
- OpenAI API pricing: https://developers.openai.com/api/docs/pricing

JobSearch does not select a paid plan, purchase credits, create provider accounts, or rotate credentials to evade quotas. Configure your own provider account and check its current model catalog.
