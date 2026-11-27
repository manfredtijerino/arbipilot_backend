# trading

The trading logic: loop, strategy, risk engine, order router, shadow fills, reconciliation, scoreboard and kill switch. Every order passes through the risk engine.

- `risk.py`: the risk engine. Limits come from `decisions.yaml`.
- `account.py`: what the account holds at one moment, as the engine sees it.
