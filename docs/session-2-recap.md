# Session 2 recap (2026-11-20 to 2026-11-26)

Stages 1 to 3 of `docs/build-roadmap.md`. All three are in `main` (pull request #1, merge commit `8bf4847`). The owner is now on branch `feature/connection-checks`, made from the updated `main`, with nothing committed on it yet.

## 1. What was built

- `docs/build-roadmap.md` — the 15 stages, each with a gate (checks green, reviewers clear, owner's Postman test, owner says "approved").
- Stage 1 (commit `215c7b8`): real database connection, startup contract proven by the owner, two health endpoints tested by him in Postman.
- Stage 2 (commit `c51dcd9`): `database/base.py`, `database/models/` (users, refresh_tokens, password_reset_codes), Alembic setup (`alembic.ini`, `database/migrations/env.py`, `safety.py`), migrations `0001` and `0002`, integration test setup against `arbipilot_test`. `config/settings.py` frozen; `database_url()` accepts only this machine's database or its test database.
- Stage 3 (commit `7a3ab99`):
  - `services/security.py` — Argon2id hashing (on two side threads), access token, refresh token, reset code.
  - `services/auth_service.py`, `services/user_service.py`, `services/errors.py`, `services/clock.py` — the login rules.
  - `database/repositories/` — users, refresh tokens, reset codes, `store.py`; row lock (`lock=True`) on the owner's row.
  - `api/dependencies.py`, `api/routes/auth.py`, `api/routes/users.py`, `api/schemas/auth.py`, `api/schemas/users.py`, `api/errors.py`.
  - `telegram_bot/alerts.py` — `send_reset_code`.
  - Tests: `tests/services/`, `tests/api/`, `tests/database/`, `tests/helpers/memory_store.py`.
  - `postman/` — Login and Users folders; `docs/api.md` — 11 built, 29 planned.
- `CLAUDE.md` — roadmap gate rule, pull-request rule, migration command, the `connection.commit()` lesson. `.claude/rules/testing.md` — never `--showlocals`.

## 2. Endpoints

| Endpoint | Test | Postman request | Owner tested |
|---|---|---|---|
| `POST /api/v1/auth/register` | Yes | Yes | Yes |
| `POST /api/v1/auth/login` | Yes | Yes | Yes |
| `POST /api/v1/auth/refresh` | Yes | Yes | Yes |
| `POST /api/v1/auth/logout` | Yes | Yes | Yes |
| `POST /api/v1/auth/password/change` | Yes | Yes | Yes |
| `POST /api/v1/auth/password/forgot` | Yes | Yes | Yes |
| `POST /api/v1/auth/password/reset` | Yes | Yes | Yes |
| `GET /api/v1/users/me` | Yes | Yes | Yes |
| `PATCH /api/v1/users/me` | Yes | Yes | Yes |

## 3. Decisions made

| Decision | Who | Why |
|---|---|---|
| Database, users and `.env` database values made by hand; Claude Code holds no AWS key | Owner | To learn |
| `.env` keeps the same key names on both machines (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`) | Owner, after trying `_DEV` names | One name, different value per machine |
| Keep the exposed development Telegram token | Owner, 2026-11-20 | Exposure was limited to the chat |
| The owner commits and pushes by hand; `main` is updated by pull request in GitHub's page | Owner, 2026-11-23 | His choice |
| Frontend is a separate repo, started after the backend is fully built | Owner | |
| Wrong passwords: growing waits 1 s, 2 s, 4 s ... up to 15 minutes | Owner, 2026-11-24 | |
| Minimum password length 12, no other rules | Owner, 2026-11-24 | |
| The reset code goes to Telegram | Owner, 2026-11-24 | Telegram is his only channel with the bot |
| Reset codes: one a minute, three an hour, ten a day, counting used and cancelled ones | Claude Code, from the security review | Otherwise the six-digit code could be guessed |
| Every login operation locks the owner's row first | Claude Code, from the security review | A token issued during a password change must not survive it |
| Unknown emails get the same growing waits (kept in memory) | Claude Code, from the security review | So the answer never shows which email exists |
| The owner builds Postman requests by hand in workspace `ArbiPilot` → collection `backend-dev` | Owner, 2026-11-24 | To learn. Give him a by-hand recipe for each new endpoint; keep `postman/` up to date as the official copy |
| Next branch is `feature/connection-checks` | Owner created it 2026-11-26 | Stage 4 |

## 4. Open questions

Waiting on the owner:
- **Say "approved" for stage 3.** He tested everything and merged, but has not said the word; the roadmap table says so.
- **Hard rule 12 wording.** It says every endpoint needs login except health; five `/auth` endpoints (register, login, refresh, forgot, reset) cannot. May Claude Code update `CLAUDE.md` and `.claude/rules/api.md` to name them? Asked three times, not answered yet.
- Still open from session 1: clock tolerance 1000 ms, how much the health endpoints say, `PGADMIN_READONLY_PASSWORD` on the laptop, `verify-full` TLS, and brief §17 questions 1, 4, 5, 6, 7, 8.

## 5. Test status

2026-11-26, on commit `7a3ab99` (same code as `main`): `ruff format --check` clean, `ruff check` clean, `pytest` 320 passed. `pytest -m integration` 13 passed on 2026-11-24 (about three minutes: every query travels to Tokyo). `security-reviewer` on stage 3: two blocking issues found and fixed, with tests.

## 6. Environments

- **Development:** `python server.py` starts with all four ✔ lines. `arbipilot_dev` holds the owner's account (one row), migrations `0001` and `0002`.
- **Test database:** `arbipilot_test`, same migrations, wiped by the integration tests.
- **Production:** nothing deployed. `arbipilot_prod` has no tables. No commit on the server.
- **Git:** `main` = `8bf4847` on GitHub and on the laptop. Current branch `feature/connection-checks` at the same commit.

## 7. Known problems

- Uncommitted on `feature/connection-checks`: `docs/build-roadmap.md`, `docs/owner-actions.md`, `docs/session-2-recap.md` (this file).
- Before the API is reachable from the internet (written in the roadmap, stage 12): no limit per caller address on `/auth`, so a stranger who knows the owner's email can keep login at the 15-minute wait and use up the reset codes; `POST /auth/register` is open to whoever calls first on a fresh production database (plan: `scripts/create_owner.py` or a one-time setup value).
- `services/auth_service.py`: the waits for unknown emails live in memory and are forgotten on restart.
- Not done from the review: a `token_version` on the user, a separate key for the reset-code HMAC, `verify-full` TLS.
- `server.py`: still no back-off and no "one Telegram alert per outage". Must be fixed before the first `/deploy`.
- `config/logging.py`: secret scrubbing is attached to the terminal handler only.
- The read-only user's rights on future `arbipilot_prod` tables are unproven until the first deploy.
- Server `Ubuntu-1` needs a restart and updates (waits for the owner's approval).
- The owner's Postman collection `backend-dev` is separate from `postman/arbipilot.postman_collection.json`; they can drift.

## 8. Next session

1. Get the owner's "approved" for stage 3 and his answer on hard rule 12; write the date in `docs/build-roadmap.md`.
2. Stage 4, connection checks, on `feature/connection-checks`: plan first, then build with `/new-endpoint`, and give the owner a by-hand Postman recipe per request.
3. Stage 5, market data. Stages 6 and 7 stay blocked until owner action 0 is done.

## 9. Owner actions

Pending, from `docs/owner-actions.md`:

| # | Action | When |
|---|---|---|
| 0 | Put `OBJECTIVES.md`, the context/decisions file and `docs/day0-recap.md` into the repo (or say where they are) | Before stage 6 |
| 2c | Replace the development Telegram bot token | Owner decided 2026-11-20 to keep it; can be revoked at any time |
| 3 | Confirm the bot token in the laptop's `.env` belongs to a development bot, not the production one | Pending confirmation |
| 4 | Add the two permanent pgAdmin connections (he uses the master user today) | Pending |
| 6 | Copy generated secrets from `.env` into the password manager. Waiting now: `JWT_SECRET` | Recurring |
| 8 | Run his Postman requests against development and say whether they pass | Before every deploy |
| 9 | Fill the production-only keys into the server's `.env` | First deploy |
| 10 | Add the server's deploy key to GitHub, if Claude Code cannot | First deploy |
| 11 | Open the SSH tunnel when Postman should reach production | After the first deploy |
| 12 | Confirm about $300 USDT and $10 BNB are in the Binance Spot wallet | Before going live |
| 13 | Tell Claude Code to go live | After the promotion criteria are met |
