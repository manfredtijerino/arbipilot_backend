---
paths:
  - "ai/**"
---

# AI layer

- AI settings (model, timeout, budget) are read in `ai/config.py`. The model name comes from `ANTHROPIC_MODEL`. Never hard-code a model name.
- Before choosing or changing the model, check Anthropic's current model list and pricing. Do not rely on memory.
- Every response is validated against a pydantic schema in `ai/schemas.py`. An invalid response counts as "skip", never as approval.
- Enforce the daily budget in `decisions.yaml` (`ai:` block): count tokens from every response, alert at 80%, stop calling at 100% until the next UTC day. Development has its own, smaller budget, because both environments spend the same monthly credit.
- The AI is a judge, not a safety dependency. On any API error, timeout or exhausted credit: open no new positions, manage existing ones by rules, alert once, never crash the loop.
- The AI's answer never bypasses the risk engine.
- Set a request timeout. A slow answer on a fast market is a skip.
- Prompts live in `ai/prompts.py`. Never include secrets or account identifiers in a prompt.
- Tests mock the client. Tests never call the real API.
