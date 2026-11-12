---
name: preflight
description: Run the lint and test gate before any commit, or when the owner asks whether the code is healthy. Use before every git commit.
---

# Preflight

Run these from the repo root, in order. Stop at the first failure.

1. `ruff format --check .`
2. `ruff check .`
3. `pytest -q`

Then report to the owner in plain language:

- **All green:** say so in one line, with the number of tests that passed. It is safe to commit.
- **Something failed:** name the step, quote the first failing test or lint error, explain in one sentence what it means, and fix it. Run the whole preflight again after the fix.

Rules:

- Never commit when any step is red.
- Never delete, skip or weaken a test to get green. If a test looks wrong, explain why and ask the owner.
- If `ruff` or `pytest` is missing, tell the owner to run `source .venv/bin/activate` and then `pip install -r requirements.txt`.
