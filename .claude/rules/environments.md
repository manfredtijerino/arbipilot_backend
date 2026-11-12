# Environments

These rules apply to every file and every command.

## The two environments
- **Development** is the owner's laptop running `python server.py` with `APP_ENV=development`, the `arbipilot_dev` database and the Binance testnet key.
- **Production** is the Lightsail server running the `app` container with `APP_ENV=production`, the `arbipilot_prod` database and the Binance mainnet keys.
- Both databases are on the same Lightsail managed PostgreSQL. There is no local database and no Docker on the laptop.

## Guard rails the code must enforce (`config/environment.py`)
- `APP_ENV=development` refuses to start with `TRADING_MODE=live`, with a database whose name ends in `_prod`, or with mainnet trade keys present.
- `APP_ENV=production` refuses to start with a database whose name ends in `_dev` or `_test`.
- Every Telegram message and every log line from development starts with `[DEV]`.
- The startup lines and `GET /api/v1/health` always state the environment.
- Dev-only endpoints return 404 in production.

## Working order
1. Build and change things in development, on a feature branch (`feature/<name>`) made from an up-to-date `main`.
2. Prove it there: `/preflight` green, and the owner's Postman requests pass against `http://localhost:3000`.
3. Merge the feature branch into `main`. `main` is the stable version and must always work.
4. Only then release with `/deploy`, from a tag on `main`.

Never fix something directly on the server. Fix it in development, test it, deploy it.

## Production protocol
- Every `ssh`, `scp` and `aws` command waits for the owner's approval. Before each one, say in one sentence what it does and what it should show.
- Before a risky production step (a migration that drops or changes a column, a restart with open live positions), take a manual database snapshot and tell the owner.
- Never run destructive SQL (`DROP`, `TRUNCATE`, `DELETE` without `WHERE`) on `arbipilot_prod`.
- Never change `TRADING_MODE` or `LIVE_CONFIRM` in production unless the owner tells you to in this session.
- After any production change, run `/deploy-check` and report the result.

## Databases
- `arbipilot_dev` — development data. Safe to reset with the owner's approval.
- `arbipilot_test` — integration tests only. Tests may wipe it freely.
- `arbipilot_prod` — production records. Never reset, never used by tests or by the laptop app.
