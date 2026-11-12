---
paths:
  - "tests/**"
---

# Testing

- Unit tests (the default `pytest` run) never touch the network: no Binance, Anthropic, Telegram, Healthchecks or database calls. External clients are replaced with fakes.
- Integration tests are marked `@pytest.mark.integration` and run with `pytest -m integration`. They use the `arbipilot_test` database only, and must refuse to run against any database whose name does not end in `_test`.
- No test ever places an order, on mainnet or testnet.
- Market data comes from recorded fixtures in `tests/fixtures/`.
- Write the test first for the risk engine, fee maths, shadow fills, reconciliation and login.
- Assert money with exact `Decimal` equality, never approximate floats.
- Each risk rule has a test for the allowed case, the blocked case and the exact boundary.
- Each endpoint has a test in `tests/api/` for success, no token and one bad input.
- Tests must pass before any commit.
- A failing test is fixed or the change is reverted. Never delete, skip or weaken a test to get green without the owner's approval.
