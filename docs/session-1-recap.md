# Session 1 recap (2026-11-12 to 2026-11-20)

Day 1 of the build plan (`docs/project-brief.md` §14), on branch `feature/foundation`. Nothing is committed yet beyond the first commit on `main`.

## 1. What was built

Earlier in the session (2026-11-12):
- Folder structure with a `README.md` per folder, `pyproject.toml`, `requirements.txt` pins.
- `config/settings.py` — every `.env` key, typed; errors name keys, never values.
- `config/environment.py` — development vs production guard rails.
- `config/logging.py` — one-line UTC log format with the `[DEV]` prefix.
- `scripts/env_status.py` — lists keys as set/empty.
- `.claude/hooks/block_secret_commit.py` — hardened; tests added.
- `.env` regrouped under section titles marked `[DEV+PROD]`, `[DEV ONLY]`, `[PROD ONLY - KEEP EMPTY HERE]`.

On 2026-11-16:
- `server.py` — the startup contract: guard rails, open the port, run the checks, print the six lines, exit 1 on a fatal failure, tell Telegram, serve.
- `config/server.py` — listening host, port binding, the FastAPI app (docs pages off, CORS only for `FRONTEND_ORIGINS`), the startup report.
- `config/database.py` — async engine over TLS, `SELECT 1` check, failure messages written by us.
- `config/settings.py` — added `database_is_configured` and `database_url()`.
- `config/version.py` — the app version (`0.1.0`).
- `config/logging.py` — quietens libraries that log web addresses and hides every secret value in every log line.
- `exchange/config.py` — Binance REST address per mode; only https and Binance's own hosts are accepted.
- `exchange/rest_client.py` — public server-time call and clock comparison (warm-up, best of three readings). No keys, no orders.
- `ai/config.py`, `ai/client.py` — Claude API check by looking the model up (no tokens).
- `telegram_bot/config.py`, `telegram_bot/alerts.py` — send a message to the owner, check the token. Send-only.
- `services/integration_service.py` — the four checks as one service, shared by startup and `/health/ready`, with a 15-second cache.
- `api/errors.py`, `api/router.py`, `api/routes/health.py`, `api/schemas/health.py` — the two health endpoints and the one error shape.
- `docs/api.md` — the endpoint table (2 built, 38 planned).
- `postman/` — the collection (Health folder) and the two environment files.
- Tests for all of the above.

## 2. Endpoints

| Endpoint | Test | Postman request |
|---|---|---|
| `GET /api/v1/health` | Yes (`tests/api/test_health.py`) | Yes |
| `GET /api/v1/health/ready` | Yes | Yes (examples for 200 and 503) |

## 3. Decisions made

| Decision | Who | Why |
|---|---|---|
| `decisions.yaml` and `config/decisions.py` move to Day 2 | Claude Code (brief open question 2 recommends it) | The source of its values (`docs/day0-recap.md`, the decisions file) is not in the repo yet |
| "Server connected successfully" means Binance is reachable and the clocks agree within 1000 ms | Claude Code, assumed from brief open question 3 — **owner to confirm** | Signed Binance requests fail when clocks disagree |
| `/health/ready` returns 503 (not 200) when any check fails | Claude Code | So Postman's status test and any monitor see the failure without reading the body |
| `/health/ready` answer is reused for 15 seconds | Claude Code | The endpoint needs no login; without this anyone reaching the port could trigger calls to Binance, Anthropic and Telegram at will |
| `/docs`, `/redoc`, `/openapi.json` are switched off | Claude Code | They would be endpoints without login (hard rule 12) |
| `BINANCE_BASE_URL` must be https and one of Binance's own hosts | Claude Code, from the trading review | A typo must never send a key to another host |
| Every log line is scrubbed of secret values | Claude Code, after the token exposure below | See "Known problems" |
| Model in `.env` is `claude-sonnet-5-5` | Set in the earlier part of the session | Confirmed present in Anthropic's model list by the live check |

## 4. Open questions

Waiting on the owner:
- Confirm the 1000 ms clock tolerance and the meaning of "Server connected" (brief question 3).
- Should the unauthenticated `/health` and `/health/ready` say less? Today `/health` shows the trading mode and `/health/ready` gives a plain reason for a failure. The security review suggests ok/failed only once the port is public. Changing it changes the documented contract.
- `PGADMIN_READONLY_PASSWORD` in the laptop's `.env` is a (read-only) production credential, which `.claude/rules/secrets.md` forbids but brief §7 prescribes. Which wins?
- Database TLS: `require` encrypts but does not verify the server's certificate. Move to `verify-full` with the AWS certificate bundle?
- Still unanswered from brief §17: 1 (starting capital), 4 (reaching the production API), 5 (database public mode), 6 (AI budget), 7 (worst-day rule), 8 (total exposure), 11 (password reset channel), 14 (server folder).

## 5. Test status

`/preflight` on 2026-11-16: `ruff format --check` clean, `ruff check` clean, `pytest` 188 passed. Integration tests: none exist yet (no database).

Both reviewers ran on the new code (`security-reviewer`, `trading-reviewer`): no blocking issues. Their hardening points were applied, except the ones listed under "Known problems".

## 6. Environments

- **Development:** `python server.py` runs the full startup. With `.env` as it is today it stops at the guard rail (mainnet read keys present). With those two keys left out for one test run: port ✔, Binance ✔, Claude ✔, database ✖ "not configured", exit code 1, and a `[DEV]` message reaches Telegram. With only the database check faked, both health endpoints answered 200 over HTTP.
- **Production:** nothing deployed. No commit on the server.
- **Database:** `arbipilot-db` exists (Lightsail, PostgreSQL 18.6, Tokyo, public mode on) with `arbipilot_dev`, `arbipilot_test`, `arbipilot_prod` and the users `arbipilot_dev`, `arbipilot_prod`, `arbipilot_readonly`. The owner created all of it by hand in the console and pgAdmin (his decision, to learn); Claude Code holds no AWS key and `scripts/db_bootstrap.py` was not written. On 2026-11-20 the development app connected for real: all startup lines ✔ and `/health/ready` 200. No tables yet.

## 7. Known problems

- **Secret exposure, 2026-11-16:** the development Telegram bot token was printed in Claude Code's command output, because `httpx` logs full request addresses at INFO and Telegram's address contains the token. It was not committed and is in no project file. Cause fixed in `config/logging.py`. Owner decision 2026-11-20: he keeps the token.
- `server.py`: no back-off and no "one Telegram alert per outage" (brief §6). Every failed start sends a message. **Must be fixed before the first `/deploy`**, where the container restarts in a loop.
- `config/logging.py`: the secret scrubbing is attached to the terminal handler. Any future second log destination (`GET /system/logs`, Alembic, scripts) needs it too; scripts do not call `setup_logging` today.
- `config/server.py`: `app.state.new_entries_enabled` is only the startup result. The Day 3 trading loop needs its own live switch in the risk engine.
- `exchange/config.py`: `MAX_CLOCK_DRIFT_MS` is a constant until `decisions.yaml` exists. `FEE_MAKER`/`FEE_TAKER` also still live in `.env` settings.
- `exchange/config.py`: only the REST address swaps for testnet. The WebSocket address swap comes with the stream (Day 2).
- `config/database.py`: the success path now runs against the real database (asyncpg with PostgreSQL 18.6 over TLS). The failure messages are still only tested with fakes.
- The read-only user's default privileges on future `arbipilot_prod` tables are set but unproven until the first tables exist.
- The mainnet read keys are still in the laptop's `.env` (owner action 2b), so `python server.py` refuses to start unless they are left out for that run.
- `config/server.py`: production listens on `0.0.0.0` inside the container, so the Docker port mapping must be `127.0.0.1:3000:3000` (to write in the compose file on Day 4).

## 8. Next session

1. Owner action 2b, so `python server.py` starts without a workaround; pgAdmin's two permanent connections (action 4).
2. `decisions.yaml` + `config/decisions.py` (needs owner action 0), then Alembic setup and the first tables.
3. Login and users (tests first), with `api/dependencies.py` requiring a token on everything except health.

## 9. Owner actions

Pending, from `docs/owner-actions.md`:

| # | Action | When |
|---|---|---|
| 2b | Clear `BINANCE_READ_KEY`, `BINANCE_READ_SECRET`, `HEALTHCHECKS_PING_URL` from the laptop's `.env` after saving them in the password manager | Now |
| 0 | Put `OBJECTIVES.md`, the context/decisions file and `docs/day0-recap.md` into the repo (or say where they are) | Before Day 2 |
| 3 | Confirm the bot token in the laptop's `.env` belongs to a development bot, not the production one | Day 1 |
| 4 | Install pgAdmin and add the two connections | After the database exists |
| 5 | Install Postman and import the collection and both environments (`postman/`) | Now possible |
| 6 | Copy generated secrets from `.env` into the password manager. Waiting now: `JWT_SECRET` | Recurring |
| 7 | Choose email and password and call `POST /auth/register` from Postman | Day 2 |
| 8 | Run the Postman requests against development and say whether they pass | Before every deploy |
| 9 | Fill the production-only keys into the server's `.env` | First deploy |
| 10 | Add the server's deploy key to GitHub, if Claude Code cannot | First deploy |
| 11 | Open the SSH tunnel when Postman should reach production | After the first deploy |
| 12 | Confirm about $300 USDT and $10 BNB are in the Binance Spot wallet | Before going live |
| 13 | Tell Claude Code to go live | After the promotion criteria are met |
