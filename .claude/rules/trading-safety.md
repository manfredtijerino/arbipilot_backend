---
paths:
  - "trading/**"
  - "exchange/**"
---

# Trading safety

Full reasoning and examples: `docs/project-brief.md` §12.

## Orders
- Every order passes through the risk engine. There is no other path to the order router.
- The risk engine enforces: position cap, daily-loss pause, exchange minimums, order-rate limits, and the kill switch.
- Maker orders use `LIMIT_MAKER`.
- Every order carries a unique client order ID, so a retry can never create a duplicate.
- Read `minNotional` and step sizes from `exchangeInfo` at startup. Skip and log any order below the minimum.
- Spot only. No withdrawal, transfer, margin or futures endpoints.

## Fills and money
- All prices, quantities, fees and balances are `Decimal`. Parse Binance's string numbers straight into `Decimal`.
- Read `commission` and `commissionAsset` on every fill. Alert when the charged rate differs from `fees` in `decisions.yaml`.
- Shadow fills use the trade-through rule with the configured delay, never touch.
- Reconcile against exchange balances. A drift above the tolerance pauses trading and alerts.

## Connections
- Before writing or changing any Binance call, check the current Binance Spot API docs. Do not rely on memory for endpoints, the user-data stream method, or rate limits.
- Expect WebSocket drops. Reconnect with backoff, then re-sync state from REST before trading again.
- Signed mainnet calls only work from the server's IP. Development uses public market data, the testnet key or fixtures.

## Modes
- `shadow`, `testnet` and `live` share one code path up to the order router.
- Never set `TRADING_MODE=live` or `LIVE_CONFIRM` unless the owner tells you to in this session. `live` is refused in development.
- The kill switch persists across restarts. Only an explicit resume re-enables entries.

## Limits
- Never loosen a value in `decisions.yaml` without the owner's explicit approval in this session.

## Review
- After changing files here, run the `trading-reviewer` subagent on the diff before committing.
