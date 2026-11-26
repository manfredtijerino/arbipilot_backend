# Owner actions

What Manfred must do by hand. Claude Code announces each one with an OWNER ACTION NEEDED block when its time comes, verifies it, then marks it done here. Source: `docs/project-brief.md` §13.

## Pending

| # | Action | When | Status |
|---|---|---|---|
| 0 | Put `OBJECTIVES.md`, the context/decisions file and `docs/day0-recap.md` into the repo (or say where they are) | Before Day 2 | Pending |
| 2c | **Replace the development Telegram bot token.** On 2026-11-16 a library logged Telegram's web address, which contains the token, and it was shown in the Claude Code chat (cause fixed the same day in `config/logging.py`). In Telegram: @BotFather → `/revoke` → choose the bot → copy the new token into `TELEGRAM_BOT_TOKEN` in the laptop's `.env` and into the password manager | Now | **Owner decision 2026-11-20: he keeps the current token and does not replace it.** The exposure was limited to the Claude Code chat; the token is in no project file. Can be revoked at any time |
| 3 | Create a development Telegram bot with @BotFather. A bot token is in the laptop's `.env` and works; waiting for him to confirm it is the development bot and not the production one | Day 1 | Pending confirmation |
| 4 | Install pgAdmin and add the two connections | Day 1, after the database exists | Pending |
| 6 | Copy each secret Claude Code generates from `.env` into his password manager. Waiting now: `JWT_SECRET` (generated 2026-11-12) | Each time one is generated | Recurring |
| 8 | Run his Postman requests against development and say whether they pass | Before every deploy | Recurring |
| 9 | Fill the production-only keys into the server's `.env`: Binance read and trade keys, production Telegram token, Healthchecks URL | First deploy | Pending |
| 10 | Add the server's deploy key to GitHub, if Claude Code cannot do it with `gh` | First deploy | Pending |
| 11 | Open the SSH tunnel when he wants Postman to reach production | After the first deploy | Pending |
| 12 | Confirm about $300 USDT and $10 BNB are in the Binance Spot wallet | Before going live | Pending |
| 13 | Tell Claude Code to go live | After the promotion criteria are met | Pending |

## Done

| # | Action | Date | How it was verified |
|---|---|---|---|
| — | Create `.venv` (Python 3.13.7) | 2026-11-12 | `.venv/bin/python --version` |
| — | Create the GitHub repo and link the folder | 2026-11-12 | `git remote -v` shows `arbipilot_backend` (push not yet tested) |
| 0a | Git name and email for this repo (owner gave the values; Claude Code set them) | 2026-11-12 | `git config user.email` prints the personal account's email |
| 0d | First commit on `main`, by hand | 2026-11-12 | `git log` shows `74bd877`, 25 files, signed with the personal email, no `.env` or `.venv` inside |
| 0c | First push of `main` to GitHub, by hand | 2026-11-12 | `git ls-remote origin` shows `refs/heads/main` at `74bd877` |
| 2 | Fill the keys only he holds into the laptop's `.env`: Binance testnet key and secret, Anthropic key, Telegram token and owner ID | 2026-11-16 | `scripts/env_status.py` shows all five set; live checks passed: Telegram `getMe` and `getChat` for the owner ID, Anthropic model list (key accepted, configured model available), Binance testnet signed account call (`canTrade` true) |
| 0b | Remote points at the personal GitHub account | 2026-11-12 | `git remote -v` shows `github.com-personal`; `git ls-remote origin` succeeds |
| 1 | Create the Lightsail managed database `arbipilot-db` (PostgreSQL 18.6, Tokyo), turn on public mode, create the three databases and three users by hand in pgAdmin, fill `POSTGRES_HOST`, `POSTGRES_PASSWORD`, `PGADMIN_READONLY_PASSWORD` in the laptop's `.env` | 2026-11-20 | `python server.py` printed `✔ Database connected successfully (arbipilot_dev)` and `GET /api/v1/health/ready` answered 200 with all four checks ok. Not yet proven: the read-only user's default privileges on future production tables |
| 2b | Clear the production-only keys from the laptop's `.env`: `BINANCE_READ_KEY`, `BINANCE_READ_SECRET`, `HEALTHCHECKS_PING_URL` | 2026-11-23 | `scripts/env_status.py` shows all three empty; the owner started `python server.py` himself and it passed the guard rail and printed all four ✔ lines |
| 5 | Install Postman. He builds the environment and the requests by hand in his own collection (workspace `ArbiPilot` → collection `backend-dev`) instead of importing the files in `postman/`; from now on each new endpoint comes with a by-hand recipe | 2026-11-25 | His screenshot of the workspace, and the stage 3 requests below reached the app |
| 7 | Choose his email and password and call `POST /auth/register` from Postman | 2026-11-25 | Read-only look at `arbipilot_dev`: one owner row, password stored as an Argon2id hash. He then ran the whole stage 3 list (login, profile, name change, refresh, forgot, reset, change password, logout); the database agrees: password changed, 5 refresh tokens issued and 0 still live, 2 reset codes issued and none unused |
