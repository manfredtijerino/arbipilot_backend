# ArbiPilot — Claude Code Setup

**Written:** 2026-11-10 · **Revised:** 2026-11-12 (v4: repo is `arbipilot_backend`, separate frontend later, one `requirements.txt`) · **Save as:** `docs/claude-code-setup.md` · **Audience:** Claude Code (to build it) and Manfred (to use it)

This file sets up Claude Code itself for the ArbiPilot repo: its standing instructions, its rules, what it is and is not allowed to do, its automatic checks, its reusable procedures and its reviewers. The project itself is described in `docs/project-brief.md`.

---

## 0. Instructions for Claude Code

1. **Do this first in session 1, before any project code.** Create every file in sections 2 to 8 exactly as written, at the path shown above each block.
2. **Check the formats against the current documentation before writing.** These features change. The pages are `code.claude.com/docs/en/memory`, `/permissions`, `/hooks`, `/skills` and `/sub-agents`. If a format here is out of date, use the current one and tell the owner what you changed.
3. **Make the two hook scripts executable:** `chmod +x .claude/hooks/*.py`.
4. **Ask the owner to exit and restart `claude`,** so the new settings, rules and hooks load.
5. **Run the checks in section 9** and show the owner each result.
6. **Commit** with the message `chore: Claude Code setup`.

The content was tested on 2026-11-11: `settings.json` parses, and both hook scripts were run against safe and unsafe commits (results in section 5).

### What changed after v4 (2026-11-12, during session 1)

The files in the repo are the source of truth; the copies printed in this document were not all rewritten.

| Before | Now | Why |
|---|---|---|
| Work on a `dev` branch, merged into `main` at release | A `feature/<name>` branch per feature, made from `main` and merged back when tested; no `dev` branch | The owner's decision |
| Claude Code commits and asks before `git push` | The owner makes most commits and every push by hand (`README.md` §2) | The owner's decision; he is learning Git |
| `Read(*.pem)`, `Read(*.key)` | `Read(**/*.pem)`, `Read(**/*.key)` | The current docs are ambiguous about subfolders |
| The commit hook scanned any `git commit` command | It also refuses a command that stages and commits together | Staged in the same command, the files were invisible to the scan (found in check 8) |
| The commit hook was described as the main guard | It only guards commits made by Claude Code; commits typed in a terminal do not pass through it | Claude Code hooks run only inside Claude Code |

### What changed in v4 (2026-11-12)

| Before | Now | Why |
|---|---|---|
| Repo and folder named `arbipilot` | `arbipilot_backend`, on the laptop and on the server | The owner created a new repo for the backend |
| One repo for everything | Backend now; a separate frontend repo later | The frontend will talk to the backend only through the API |
| `requirements.txt` plus `requirements-dev.txt`, written by Claude Code | One `requirements.txt`, created by the owner | His decision; testing tools sit at the bottom of the same file |

### What changed in v3 (2026-11-11)

| Before | Now | Why |
|---|---|---|
| Claude Code could not read or edit `.env` | It can read and edit `.env`, on the laptop and on the server | The owner supervises and Claude Code does the work |
| The owner ran most commands | Claude Code runs them; the owner approves the ones that touch production | Same reason |
| Manual steps were mentioned in passing | Every manual step is shown in an OWNER ACTION NEEDED block and tracked in `docs/owner-actions.md` | So nothing the owner must do is ever missed |
| One environment, database in Docker | Development and production, both databases on one cloud managed database | Nothing runs locally except the app and its tests |
| No API rules | An API rule file, a `/new-endpoint` skill and a security reviewer | Every endpoint ships with a test and a Postman request |

---

## 1. What gets created

```
arbipilot_backend/
├── CLAUDE.md
└── .claude/
    ├── settings.json
    ├── settings.local.json      (created later by Claude Code; never committed)
    ├── rules/
    │   ├── secrets.md           always loaded
    │   ├── environments.md      always loaded
    │   ├── api.md
    │   ├── database.md
    │   ├── trading-safety.md
    │   ├── ai-layer.md
    │   ├── python-style.md
    │   └── testing.md
    ├── hooks/
    │   ├── block_secret_commit.py
    │   └── format_python.py
    ├── skills/
    │   ├── preflight/SKILL.md
    │   ├── new-endpoint/SKILL.md
    │   ├── deploy/SKILL.md
    │   ├── deploy-check/SKILL.md
    │   └── session-recap/SKILL.md
    └── agents/
        ├── trading-reviewer.md
        └── security-reviewer.md
```

Each piece does a different job:

| Piece | What it is | Why we need it | Example |
|---|---|---|---|
| `CLAUDE.md` | A short note Claude Code reads at the start of every session | Because each session starts with no memory of the last one | It already knows development is the laptop and production is the server |
| `.claude/rules/` | Extra instructions, some always loaded and some only for certain folders | Because loading every rule all the time makes instructions long, and long instructions get followed less well | The API rules load only when it opens a file in `api/` |
| `settings.json` permissions | A list of what Claude Code may do freely, must ask about, or can never do | Because these are enforced by the program itself, so they hold even if an instruction is forgotten | Every `ssh` command to the server waits for your approval |
| Hooks | Small scripts that run automatically at set moments | Because an automatic check never forgets | A commit containing a key is stopped before it happens |
| Skills | Saved step-by-step procedures, run with `/name` | Because a repeated procedure should be done the same way every time | `/deploy` releases to production in the same 14 steps every time |
| Subagents | A second, read-only Claude that reviews the work | Because the author of code is the worst reviewer of it | `security-reviewer` checks that no endpoint can be called without logging in |

Instructions and permissions are different things. `CLAUDE.md` and the rules are advice that Claude Code reads and normally follows. Permissions and hooks are enforced. Anything that protects money or secrets is in both.

---

## 2. `CLAUDE.md`

- **Why:** it is the one file loaded in full at the start of every session.
- **Keep it under 200 lines.** The documentation says longer files use more context and are followed less reliably.
- **It points to the other documents** and does not copy them, because one source of truth cannot contradict itself.
- **It contains the "Where things live" table,** so both you and Claude Code can find the database config, the server config, the AI config or any function in one look.

**Path:** `CLAUDE.md`

````markdown
# ArbiPilot backend

This repo, `arbipilot_backend`, is the backend of ArbiPilot: a personal, single-user, AI-assisted crypto trading bot for Binance Spot. A separate frontend repo will be built later and will talk to this backend only through the API. Python 3.13, FastAPI on port 3000, PostgreSQL on a Lightsail managed database, one Lightsail server in Tokyo. Trading modes: `shadow` (pretend orders on real data), `testnet`, `live`.

The owner supervises. You write all the code, manage `.env`, and configure the server and the database. When something needs his hands, you tell him (see "Owner actions").

## Read before working

Read these when a task touches their topic. Do not guess what they say.

- `OBJECTIVES.md` — goals and the trading strategy. Wins on strategy questions.
- The context/decisions file — decisions 1–27.
- `docs/day0-recap.md` — provider status, key names, IPs, fees, `decisions.yaml` values.
- `docs/project-brief.md` — environments, stack, folder layout, endpoints, build plan, open questions.
- `docs/claude-code-setup.md` — how this `.claude/` folder is built and maintained.
- `docs/api.md` — the endpoint table. `docs/owner-actions.md` — what the owner still has to do.
- The latest `docs/session-N-recap.md` — where the previous session stopped.

If two files disagree and `docs/project-brief.md` §0 does not settle it, stop and ask the owner.

## Environments

| | Development | Production |
|---|---|---|
| App runs on | The owner's laptop: `python server.py` | Lightsail server `Ubuntu-1`: Docker service `app` |
| `APP_ENV` | `development` | `production` |
| Database | `arbipilot_dev` | `arbipilot_prod` |
| Binance | Testnet key and public market data | Mainnet keys (IP-locked to the server) |
| `TRADING_MODE` | `shadow` or `testnet`; `live` is refused | `shadow` until the owner goes live |
| `.env` | The one in this folder | `~/arbipilot_backend/.env` on the server |

- Nothing else runs on the laptop: no local database and no Docker.
- All work starts in development. Production changes only through `/deploy`.
- The development app never connects to `arbipilot_prod`. Integration tests use `arbipilot_test` only.

## Commands

| Purpose | Command |
|---|---|
| Activate environment | `source .venv/bin/activate` |
| Install libraries | `pip install -r requirements.txt` |
| Run the backend (development) | `python server.py` |
| Which `.env` keys are set (no values shown) | `python scripts/env_status.py` |
| Unit tests | `pytest` |
| Integration tests (use `arbipilot_test`) | `pytest -m integration` |
| Lint / format | `ruff check .` · `ruff format .` |
| New migration | `alembic revision --autogenerate -m "<message>"` |
| Apply migrations (development) | `alembic upgrade head` |
| Release to production | `/deploy` |

## Where things live

| Looking for | Go to |
|---|---|
| Where the app starts | `server.py` |
| Every `.env` key | `config/settings.py` |
| Development vs production rules | `config/environment.py` |
| Database connection | `config/database.py` |
| Server host, port, app setup | `config/server.py` |
| Risk limits | `decisions.yaml`, loaded by `config/decisions.py` |
| Every endpoint | `api/router.py`, then `api/routes/` |
| Request and response shapes | `api/schemas/` |
| Tables | `database/models/` |
| Database queries | `database/repositories/` |
| Table changes | `database/migrations/` |
| Login, users, system functions | `services/` |
| AI model, budget, prompts | `ai/` (`ai/config.py` first) |
| Telegram | `telegram_bot/` (never name a folder `telegram`) |
| Binance | `exchange/` |
| Strategy, risk engine, orders | `trading/` |
| One-off commands | `scripts/` |
| Postman collection and environments | `postman/` |

Each folder has a `README.md` of a few lines saying what belongs there. Lowercase paths everywhere.

## Hard rules

1. Secrets live only in `.env` (laptop and server). You may read and edit `.env`. Never show a secret value in chat, in command output, in logs, in docs, in Postman files or in a commit.
2. Never commit `.env`. There is one `.env` per machine and no template file.
3. Never set `TRADING_MODE=live` or `LIVE_CONFIRM` unless the owner tells you to in this session, in his own words.
4. Never loosen a limit in `decisions.yaml` without the owner's explicit approval.
5. Every order passes through the risk engine. No exceptions.
6. Unit tests never touch the network. No test ever places an order or touches `arbipilot_dev` or `arbipilot_prod`.
7. Spot trading only. No withdrawals, transfers, margin or futures code.
8. Production is changed only through `/deploy`, and every command on the server or on AWS waits for the owner's approval.
9. Never delete the managed database, a database, a snapshot, the server or `.venv/`.
10. Never build deferred items (B2, Sentry, Tailscale, dashboard, Cloudflare) until the owner starts the pre-live bundle.
11. Money is `Decimal`, never `float`. Timestamps are UTC.
12. Every endpoint requires login except the health endpoints.

Topic rules live in `.claude/rules/`. Procedures live in `.claude/skills/`. Reviewers live in `.claude/agents/`.

## Owner actions

You do everything you can do yourself. When a step needs the owner, stop and show this block, then add it to `docs/owner-actions.md`:

```
OWNER ACTION NEEDED
What:        <one sentence>
Why you:     <why Claude Code cannot do it>
Steps:       1. ...  2. ...
You will see: <what success looks like>
Then tell me: "done"
```

Never bury a manual step inside a long answer. Never assume he did it: verify, then mark it done.

## How to work

- Start every session in plan mode. Present the plan and wait for approval.
- There is one `requirements.txt` and no `requirements-dev.txt`. To add a library: add its line to the file, run `pip install -r requirements.txt`, and tell the owner what you added and why.
- No frontend code in this repo. Anything the frontend needs is an endpoint, documented in `docs/api.md`.
- Verify library versions and external API behaviour against current docs. Do not rely on memory for Binance, AWS, Anthropic or library details.
- Write tests first for the risk engine, fee maths, shadow fills and login.
- Use `/new-endpoint` for every endpoint, so its test and its Postman request are created with it.
- After changing `trading/`, `exchange/` or `ai/`, run the `trading-reviewer` subagent. After changing `api/`, `services/`, `config/` or `database/`, run the `security-reviewer` subagent. Fix every blocking issue.
- Run `/preflight` before every commit. Never commit on red.
- Small commits on the `dev` branch, one concern each. Ask before `git push`.
- End every session with `/session-recap`.
- When you learn a project-specific lesson, add one line here. Remove rules that no longer apply. Keep this file under 200 lines.

## Talking to the owner

Manfred is the only user and is not a professional Python or DevOps engineer. Explain in plain language, say why, and give one concrete example. When you run something for him, say what you ran and what it showed. Never assume he will debug by hand.
````

---

## 3. Rules — `.claude/rules/`

- **Why:** a rule file with a `paths:` header loads only when Claude Code reads a matching file. A rule file without that header loads at the start of every session.
- **Example:** `testing.md` stays out of the way while it writes a route, then loads the moment it opens anything in `tests/`.

| File | Loads when | Covers |
|---|---|---|
| `secrets.md` | Always | How Claude Code handles `.env` and every secret |
| `environments.md` | Always | Development vs production, and the production protocol |
| `api.md` | Reading `api/**`, `services/**` or `postman/**` | Endpoint shape, login, Postman |
| `database.md` | Reading `database/**`, `config/database.py`, `alembic.ini` or `scripts/db_*.py` | The managed database, roles, migrations |
| `trading-safety.md` | Reading `trading/**` or `exchange/**` | Orders, fills, money, modes, limits |
| `ai-layer.md` | Reading `ai/**` | Model choice, budget, failure behaviour |
| `python-style.md` | Reading any `.py` file | `Decimal`, UTC, async, settings |
| `testing.md` | Reading `tests/**` | Unit vs integration tests, fixtures, boundaries |

**Path:** `.claude/rules/secrets.md`

````markdown
# Secrets

These rules apply to every file and every command.

## What you may do
- You may read and edit `.env` on the laptop, and `~/arbipilot_backend/.env` on the server over SSH with the owner's approval.
- There is exactly one `.env` per machine. Do not create `.env.example` or any other copy or template.
- The list of keys is the `Settings` class in `config/settings.py`. Every field has a type and a comment.
- When a new setting is needed: add the field to `Settings`, add the line to the laptop's `.env`, and add it to the server's `.env` at the next `/deploy`.
- You may generate secrets yourself (`JWT_SECRET`, database passwords). Use `secrets.token_urlsafe(48)` or `openssl rand -hex 32`, write the value straight into `.env`, and never display it.

## What you must never do
- Never show a secret value in chat, in your own summaries, or in a command's output. Say "set" or "empty", never the value.
- Prefer `python scripts/env_status.py` (key names and set/empty only) when you only need to know what is configured.
- Never run a command whose output would display secrets: `cat .env`, `env`, `printenv`, `docker compose config`, `echo $KEY`.
- Never commit `.env`, `.env.*`, `*.pem` or `*.key`. Never read `*.pem`, `*.key` or `~/.ssh/`.
- Never put a secret in code, tests, fixtures, logs, error messages, commit messages, docs or Postman files.
- Never copy the laptop's `.env` to the server or the server's to the laptop. They hold different values on purpose.
- Never put production database or Binance mainnet credentials in the laptop's `.env`.
- Never log a full connection string. Log the host, port and database name only.
- If the commit hook blocks a commit, fix the cause. Never bypass or disable the hook.

## Secrets only the owner has
Binance keys, the Telegram bot tokens and the Anthropic key are in the owner's password manager. Do not ask him to paste them into chat. Show an OWNER ACTION NEEDED block naming the `.env` key to fill, then verify with `scripts/env_status.py` and a live connection check.

## After you create a secret
Tell the owner which key you created and ask him to copy it from `.env` into his password manager. If a secret is ever exposed (shown, logged or committed), tell him at once and help him rotate it.

## Tests and examples
Use obviously fake short values such as `"test-key"`. Never a real-looking long string.
````

**Path:** `.claude/rules/environments.md`

````markdown
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
1. Build and change things in development, on the `dev` branch.
2. Prove it there: `/preflight` green, and the owner's Postman requests pass against `http://localhost:3000`.
3. Only then release with `/deploy`.

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
````

**Path:** `.claude/rules/api.md`

````markdown
---
paths:
  - "api/**"
  - "services/**"
  - "postman/**"
---

# API

Use the `/new-endpoint` skill for every endpoint. The endpoint table is `docs/api.md`.

## Shape
- All routes are under `/api/v1`. Every route is registered in `api/router.py`, so that file is the map.
- Routes are thin: validate input, call a function in `services/`, `trading/`, `exchange/` or `ai/`, return a schema. No business logic and no SQL in a route.
- Every request body and every response has a pydantic schema in `api/schemas/`.
- Errors use one shape: `{"error": {"code": "...", "message": "..."}}`, with a plain-language message.
- Lists are paginated (`limit`, `offset`) and return newest first.
- Money is returned as a string, never a JSON number. Times are ISO 8601 UTC.

## Security
- Every route requires a valid access token except `GET /api/v1/health` and `GET /api/v1/health/ready`.
- No response ever contains a secret, a password hash, a token other than the caller's own, or a full connection string.
- Passwords are hashed with Argon2. Never store, log or return a password.
- Login and password-reset endpoints are rate limited, and answer the same way whether or not the account exists.
- Registration is closed once the owner account exists.
- There is no endpoint that switches to live trading or changes a risk limit.
- Dev-only routes (test order, sample AI evaluation) return 404 when `APP_ENV=production`.
- Outside production the app listens on `127.0.0.1` only.
- Browser access (CORS) is allowed only for the addresses listed in `FRONTEND_ORIGINS`. Never use `*`.

## The frontend
- The frontend is a separate repo, built later. This API is its only way in, so `docs/api.md` is the contract between the two.
- Never change or remove a field in a response without telling the owner; add new fields instead, or add a new route.
- No HTML, templates or frontend assets in this repo.

## Tests and Postman
- Every route has a test in `tests/api/` for the success case, the unauthenticated case and one bad input.
- Every route has a request in `postman/arbipilot.postman_collection.json`, in the folder matching its group, with a saved example and a status-code test.
- Postman requests use `{{base_url}}` and `{{access_token}}`. The login request stores the token in the environment by script.
- The two environment files in `postman/` hold variable names with empty values. Never save a real token, password or key in them.
- Update the collection and `docs/api.md` in the same commit as the route.
````

**Path:** `.claude/rules/database.md`

````markdown
---
paths:
  - "database/**"
  - "config/database.py"
  - "alembic.ini"
  - "scripts/db_*.py"
---

# Database

- PostgreSQL runs on one Lightsail managed database holding `arbipilot_dev`, `arbipilot_test` and `arbipilot_prod`. Nothing runs locally.
- Roles: `arbipilot_dev` (dev and test databases), `arbipilot_prod` (production database only), `arbipilot_readonly` (read-only on production, for the owner's pgAdmin). The master user is used only by `scripts/db_bootstrap.py`.
- All connections use TLS (`POSTGRES_SSLMODE=require` or stricter).
- Every schema change is an Alembic migration in `database/migrations/`. Never change tables by hand, in pgAdmin, or with `create_all` outside tests.
- Never edit a migration that has already been applied. Write a new one.
- A migration runs in development first. It reaches production only through `/deploy`.
- Ask the owner before any downgrade or any migration that drops or changes a table or column. Take a manual snapshot first.
- Money columns are `NUMERIC`, never floating point. Timestamps are `TIMESTAMPTZ`.
- Tables live in `database/models/`, one file per table. Queries live in `database/repositories/`. No SQL anywhere else.
- The connection URL is built in `config/settings.py` from separate `.env` values. Never log it.
- Never delete the managed database, a database or a snapshot.
- The laptop is far from Tokyo, so each development query takes a noticeable fraction of a second. Batch queries and never loop one query per row.
````

**Path:** `.claude/rules/trading-safety.md`

````markdown
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
````

**Path:** `.claude/rules/ai-layer.md`

````markdown
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
````

**Path:** `.claude/rules/python-style.md`

````markdown
---
paths:
  - "**/*.py"
---

# Python style

- Python 3.13. Type hints on every function signature.
- Money is `Decimal`, never `float`. Build from strings: `Decimal("0.00075")`.
- Timestamps are timezone-aware UTC: `datetime.now(UTC)`. Never naive datetimes.
- I/O is async (`httpx.AsyncClient`, `asyncpg`, `websockets`). Never block the event loop with `time.sleep` or sync HTTP.
- Settings come from `config/settings.py`. Never call `os.environ` elsewhere.
- Risk values come from `config/decisions.py`. Never hard-code a limit, fee or threshold.
- `server.py` wires things together and holds no business logic. Routes in `api/` are thin; functions live in `services/`, `trading/`, `exchange/` and `ai/`.
- Every package folder has an `__init__.py` and a short `README.md` saying what belongs there.
- Catch specific exceptions. Never use a bare `except:` or swallow an error silently.
- Use `logging` with structured, single-line messages. No `print` outside the startup status lines in `server.py`.
- Import the Telegram library as `telegram`; our own package is `telegram_bot`.
- `ruff` formats and lints. Do not hand-format against it.
- Libraries are listed in the single `requirements.txt`. Never create a second requirements file, and never run `pip freeze > requirements.txt`.
````

**Path:** `.claude/rules/testing.md`

````markdown
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
````

---

## 4. Permissions and hooks — `.claude/settings.json`

This file is committed, so the same protections apply on any machine that clones the repo.

**Path:** `.claude/settings.json`

````json
{
  "permissions": {
    "deny": [
      "Read(**/*.pem)",
      "Read(**/*.key)",
      "Read(~/.ssh/**)",
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(aws lightsail delete-*)",
      "Bash(dropdb *)",
      "Bash(cat .env)",
      "Bash(printenv *)"
    ],
    "ask": [
      "Bash(git push *)",
      "Bash(ssh *)",
      "Bash(scp *)",
      "Bash(aws *)",
      "Bash(psql *)",
      "Bash(alembic downgrade *)",
      "Bash(rm -rf *)"
    ],
    "allow": [
      "Bash(pytest *)",
      "Bash(python -m pytest *)",
      "Bash(ruff *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git switch *)",
      "Bash(pip install -r *)",
      "Bash(python scripts/env_status.py)",
      "Bash(alembic upgrade head)",
      "Bash(alembic current)",
      "Bash(alembic history *)",
      "Bash(alembic revision *)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/hooks/block_secret_commit.py\"",
            "timeout": 30
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/hooks/format_python.py\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
````

### How the permission lists work

Claude Code checks the lists in a fixed order: **deny first, then ask, then allow**. The first match wins, so an allow rule can never override a deny or an ask.

| List | Meaning | What is in it | Why |
|---|---|---|---|
| **deny** | Never, not even with approval | Reading key files and `~/.ssh` · force-push · deleting anything on AWS · dropping a database · printing `.env` or the environment | Because these expose secrets or destroy things that cannot be recovered |
| **ask** | Stops and asks you each time | `git push` · `ssh` · `scp` · every `aws` command · `psql` · database downgrade · `rm -rf` | Because these reach production or AWS, and supervising means seeing them first |
| **allow** | Runs without asking | Tests, lint, local git, installing from the requirements files, development migrations, the masked `.env` status script | Because these are safe, stay in development and happen often |

Anything not in a list follows Claude Code's normal behaviour, which is to ask. That includes editing `.env`: it is permitted, and you see the edit before it is applied.

**Supervising means approving.** You no longer type the commands, but each one that touches the server or AWS appears for a yes or no, with a sentence from Claude Code saying what it does. Prefer plain "Yes". Choosing "Yes, and don't ask again" writes a permanent allow rule into `.claude/settings.local.json`; never choose it for `ssh`, `aws` or `git push`.

### Letting Claude Code read `.env`: what it means

You asked for this, and the setup now allows it. Three things follow, and you should know them:

| Consequence | What it means | What reduces it |
|---|---|---|
| Secret values enter the Claude Code conversation | When Claude Code opens `.env`, the values become part of the session that is sent to Anthropic to be processed, like everything else it reads | It uses `scripts/env_status.py`, which shows only key names and set/empty, whenever that is enough |
| A value could be repeated by mistake | For example in a summary or an error message | The rule in `secrets.md` forbids showing values; `cat .env` and `printenv` are denied outright |
| A value could end up in a file | For example pasted into a test or a Postman file | The commit hook in section 5 blocks it |

The laptop's `.env` holds development values only: the testnet key and the development database. The mainnet trade key lives only on the server, has no withdrawal permission and works only from the server's address. That limits what a leak from the laptop could do.

### What the permissions do not cover

| Gap | Example | What covers it |
|---|---|---|
| Bash rules match the command as typed, not every way to run a program | `git -C . push` does not match `Bash(git push *)` | Claude Code's default is still to ask for unlisted commands |
| What runs inside an `ssh` command is not checked separately | `ssh arbipilot "docker compose down"` | Every `ssh` command asks, and you see the full text before approving |
| A secret can be typed into an ordinary file | A token saved in a Postman environment | The commit hook in section 5 |

For stronger, operating-system-level isolation, Claude Code has a sandbox mode (`code.claude.com/docs/en/sandboxing`). It is optional and not part of this setup; consider it before the bot holds real money.

### The two hooks

| Hook | Runs | What it does | Why |
|---|---|---|---|
| `block_secret_commit.py` | Before every shell command; acts only on `git commit` | Stops the commit if a secret file or a real-looking secret is about to be committed | Because Claude Code now handles `.env` directly, so this is the main guard against a key reaching GitHub |
| `format_python.py` | After every file edit | Formats the file with `ruff` if it is a `.py` file | Because consistent formatting keeps the diffs you review small |

---

## 5. Hook scripts — `.claude/hooks/`

Both scripts use only Python's standard library, so they need nothing installed beyond the Python you already have. A hook blocks an action by exiting with code 2; the message it prints is shown to Claude Code as the reason.

**Path:** `.claude/hooks/block_secret_commit.py`

````python
#!/usr/bin/env python3
"""PreToolUse hook: stop a git commit that would include a secret.

Runs before every Bash command and only acts on `git commit`.
Exit code 2 blocks the command and shows the reason to Claude.
This is a heuristic safety net, not a guarantee.
"""

import json
import os
import re
import subprocess
import sys

BLOCKED_NAMES = re.compile(r"(^|/)\.env(\..*)?$|\.(pem|key)$")

SPECIFIC = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "login token (JWT)",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
        ),
    ),
    (
        "database URL with a password",
        re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s:/@]+:[^\s@{}$<>]{12,}@"),
    ),
]
NAME = r"[A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)[A-Za-z0-9_]*"
QUOTED = re.compile(rf"(?i)\b{NAME}[\"']?\s*[=:]\s*[\"'][A-Za-z0-9_\-:/+]{{24,}}[\"']")
UNQUOTED = re.compile(rf"(?i)\b{NAME}\s*[=:]\s*[A-Za-z0-9_\-:/+]{{24,}}")
POSTMAN_ENV = re.compile(r"(^|/)postman/.*environment.*\.json$")
POSTMAN_VALUE = re.compile(r"\"value\"\s*:\s*\"(?!https?://|\{\{)[^\"]{16,}\"")


def git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def scan(diff: str) -> list[str]:
    problems: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
            continue
        if not line.startswith("+") or not current:
            continue
        added = line[1:]
        for label, pattern in SPECIFIC:
            if pattern.search(added):
                problems.append(f"{current}: looks like this secret: {label}")
        if POSTMAN_ENV.search(current) and POSTMAN_VALUE.search(added):
            problems.append(
                f"{current}: a Postman environment value is saved (leave values empty)"
            )
        if current.endswith(".py"):
            generic_hit = QUOTED.search(added)
        else:
            generic_hit = QUOTED.search(added) or UNQUOTED.search(added)
        if generic_hit:
            problems.append(
                f"{current}: a key/secret/token/password has a real-looking value"
            )
    return problems


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", command):
        return 0

    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    include_unstaged = bool(re.search(r"\s(-[A-Za-z]*a[A-Za-z]*|--all)\b", command))

    names = git(["diff", "--cached", "--name-only"], cwd).splitlines()
    diff = git(["diff", "--cached", "-U0"], cwd)
    if include_unstaged:
        names += git(["diff", "--name-only"], cwd).splitlines()
        diff += "\n" + git(["diff", "-U0"], cwd)

    problems = [
        f"{n}: secret files are never committed"
        for n in names
        if BLOCKED_NAMES.search(n)
    ]
    problems += scan(diff)
    if not problems:
        return 0

    unique = list(dict.fromkeys(problems))
    print("Commit blocked: possible secret in the commit.", file=sys.stderr)
    for problem in unique[:10]:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "Remove it (git restore --staged <file>, or delete the value), then commit again.",
        file=sys.stderr,
    )
    print(
        "Do not bypass this hook. If a real key was exposed, tell the owner to rotate it.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
````

**Path:** `.claude/hooks/format_python.py`

````python
#!/usr/bin/env python3
"""PostToolUse hook: format a Python file right after Claude edits it.

Formatting only. Lint fixes are left to /preflight, because auto-removing
"unused" imports in the middle of a multi-step edit deletes code that the
next edit needs. Never blocks. If ruff is not installed yet, it does nothing.
"""

import json
import os
import shutil
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path.endswith(".py") or not os.path.isfile(path):
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    venv_ruff = os.path.join(project, ".venv", "bin", "ruff")
    ruff = venv_ruff if os.path.isfile(venv_ruff) else shutil.which("ruff")
    if not ruff:
        return 0

    subprocess.run(
        [ruff, "format", "--quiet", path], cwd=project, capture_output=True, check=False
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

### Test results (2026-11-11)

| Case | Expected | Result |
|---|---|---|
| `.env` staged | Blocked | Blocked |
| Settings code that builds the database URL from variables | Allowed | Allowed |
| A real database URL with a password, in a notes file | Blocked | Blocked |
| A placeholder URL in docs (`postgresql://user:password@host`) | Allowed | Allowed |
| Postman environment with empty values and `{{variables}}` | Allowed | Allowed |
| Postman environment with a saved login token | Blocked | Blocked |
| Postman environment with a saved password | Blocked | Blocked |
| Postman collection using `{{base_url}}` and `{{access_token}}` | Allowed | Allowed |
| A `.json` file with a long API key | Blocked | Blocked |
| A file with an AWS access key | Blocked | Blocked |
| Ordinary login code (`hashed_password = hash_password(...)`) | Allowed | Allowed |
| Docs that name keys with empty or placeholder values | Allowed | Allowed |

Earlier tests, still valid: ordinary commits pass, a non-commit command is ignored, `.pem` files and Anthropic keys are blocked, `git commit -am` is covered, and the format hook tidies a `.py` file without removing imports.

Two honest limits:

- **The commit hook is a pattern check.** It catches secret files, Anthropic keys, Telegram tokens, AWS keys, login tokens, database URLs with passwords, saved Postman values, and any name containing KEY, SECRET, TOKEN or PASSWORD followed by a long value. A secret in an unusual shape could pass. It is a safety net under the rules, not a replacement for them.
- **The format hook only formats.** It does not auto-fix lint errors, because removing "unused" imports in the middle of a multi-step edit deletes code the next edit needs. Lint runs in `/preflight`.

---

## 6. Skills — `.claude/skills/`

- **Why:** a skill is a saved procedure. You run it by typing `/` and its name, and Claude Code follows the same steps every time.
- **Two kinds here:** `preflight` and `new-endpoint` can also be started by Claude Code on its own, because they belong to everyday work. `deploy`, `deploy-check` and `session-recap` only run when you type them, because they reach production or write a record.

| Skill | You type | When | What you get |
|---|---|---|---|
| `preflight` | `/preflight` | Before every commit, or whenever you want to know if the code is healthy | "All green, 42 tests passed", or the first failure explained |
| `new-endpoint` | `/new-endpoint` | Whenever an endpoint is added or changed | The route, its test, its Postman request and its row in `docs/api.md`, all together |
| `deploy` | `/deploy` | When development is tested and you want it in production | A release summary to approve, then the release, then the checks |
| `deploy-check` | `/deploy-check` | After a deploy, or any time you want to verify production | A pass or fail table for eleven checks |
| `session-recap` | `/session-recap 1` | At the end of each session | `docs/session-1-recap.md`, updated docs, and a commit |

**Path:** `.claude/skills/preflight/SKILL.md`

````markdown
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
````

**Path:** `.claude/skills/new-endpoint/SKILL.md`

````markdown
---
name: new-endpoint
description: Add or change an API endpoint the standard way, with its test and its Postman request. Use whenever creating or modifying anything under api/.
---

# New endpoint

Follow every step. An endpoint is not finished until the owner can run it from Postman.

1. **Schema** — define the request and response shapes in `api/schemas/<group>.py`.
2. **Function** — put the logic in `services/`, `trading/`, `exchange/` or `ai/`. The route only validates, calls the function and returns the schema.
3. **Route** — add it to `api/routes/<group>.py` under `/api/v1`, and make sure the group is registered in `api/router.py`.
4. **Protection** — require a valid access token unless it is a health endpoint. If it is dev-only, return 404 when `APP_ENV=production`.
5. **Tests** — in `tests/api/test_<group>.py`: the success case, the no-token case, and one bad input.
6. **Postman** — add the request to `postman/arbipilot.postman_collection.json` in the folder for its group:
   - URL uses `{{base_url}}`; the `Authorization` header uses `Bearer {{access_token}}`.
   - Include an example body, a saved example response and a test that checks the status code.
   - Never save a real token, password or key.
7. **Docs** — add or update its row in `docs/api.md`: method, path, login needed, dev-only or not, what it does.
8. **Prove it** — start the app in development, call the endpoint, and show the owner the request and the response (with any token masked).
9. **Gate** — run `/preflight`.

Then tell the owner: "Re-import the Postman collection to see the new request", and where to find it.
````

**Path:** `.claude/skills/deploy/SKILL.md`

````markdown
---
name: deploy
description: Release tested code from development to production. Use only when the owner asks to deploy or release.
disable-model-invocation: true
---

# Deploy to production

Stop at the first failure and tell the owner. Every `ssh`, `scp` and `aws` command waits for his approval; before each one, say what it does and what it should show.

## 1. Before leaving the laptop

1. `git status` is clean and the branch is `dev`.
2. `/preflight` is green, and `pytest -m integration` passes.
3. Ask the owner: "Have your Postman requests passed against development?" Do not continue without a yes.
4. Reviews since the last release: `trading-reviewer` says SAFE TO COMMIT for any change in `trading/`, `exchange/` or `ai/`; `security-reviewer` says SAFE for any change in `api/`, `services/`, `config/` or `database/`.
5. Show the owner a release summary in plain language: the commits, new `.env` keys, new migrations, and anything that restarts. Wait for "yes, deploy".

## 2. Release

6. Merge `dev` into `main`, tag it `release-YYYYMMDD-N`, and `git push` with tags.
7. If a migration drops or changes a column, or live positions are open: take a manual database snapshot first and tell the owner its name.
8. On the server: `cd ~/arbipilot_backend && git fetch --tags && git checkout <tag>`.
9. New `.env` keys: add them to the server's `.env` with production values. Never copy the laptop's file. Verify with `python scripts/env_status.py` inside the container.
10. Migrations: `docker compose run --rm app alembic upgrade head`.
11. Restart: `docker compose up -d --build app`.

## 3. After

12. Run `/deploy-check`.
13. Add a line to `docs/deploys.md`: date, tag, migrations, result.
14. Tell the owner what is now live and what he should see in Telegram.

## Rollback

If a check fails after the restart: check out the previous tag on the server, rebuild, and run `/deploy-check` again. Do not downgrade the database without the owner's approval; say plainly if the old code cannot run on the new tables.

## Never during a deploy

- Never change `TRADING_MODE` or `LIVE_CONFIRM`.
- Never edit code on the server.
- Never deploy from a branch other than `main`, or with failing tests.
- If live positions are open, ask the owner before restarting, and say what the restart interrupts.
````

**Path:** `.claude/skills/deploy-check/SKILL.md`

````markdown
---
name: deploy-check
description: Verify the production server step by step. Use after a deploy, or when the owner asks to check production.
disable-model-invocation: true
---

# Deploy check

Every command on the server needs the owner's approval. Show each command and what it should print before running it. Never print `.env`.

Run on the server (`ssh arbipilot`, in `~/arbipilot_backend`):

| # | Check | Command | Pass when |
|---|---|---|---|
| 1 | Container is up | `docker compose ps` | `app` is running and healthy |
| 2 | Startup lines | `docker compose logs --tail 60 app` | Four ✔ lines, `Environment: PRODUCTION`, the database is `arbipilot_prod`, and the mode the owner expects |
| 3 | Liveness | `curl -s http://127.0.0.1:3000/api/v1/health` | `environment` is `production` |
| 4 | Readiness | `curl -s http://127.0.0.1:3000/api/v1/health/ready` | Database, Binance, Claude and Telegram are all `ok` |
| 5 | Port 3000 is private | `ss -ltn` | Port 3000 listens on `127.0.0.1` only, never `0.0.0.0` |
| 6 | Right code | `git describe --tags` | It prints the release tag just deployed |
| 7 | Migrations applied | `docker compose run --rm app alembic current` | It shows the latest revision (head) |
| 8 | Server address | `curl -s https://checkip.amazonaws.com` | `13.193.72.121`, the address the Binance keys are locked to |
| 9 | Clock is synced | `chronyc tracking` | `Leap status: Normal` |
| 10 | SSH is key-only | `sudo sshd -T` and look for `passwordauthentication` | The value is `no` |
| 11 | Restart survives | `docker compose restart app`, then repeat checks 2 to 4 | Same results. Skip if live positions are open, unless the owner agrees. |

Ask the owner to confirm two things himself:

- Telegram received the production startup message with the correct mode.
- Healthchecks.io shows the check as "up" with a recent ping.

Report a table of pass or fail for each check. For every failure, explain what it means in one sentence and propose the fix. Fix it in development and redeploy; do not patch the server by hand.
````

**Path:** `.claude/skills/session-recap/SKILL.md`

````markdown
---
name: session-recap
description: Write the end-of-session recap file so the next session can continue where this one stopped.
disable-model-invocation: true
argument-hint: [session-number]
---

# Session recap

Write `docs/session-$ARGUMENTS-recap.md`. If no number was given, use the next number after the latest recap in `docs/`.

Use exactly these sections:

1. **What was built** — files created or changed, one line each.
2. **Endpoints** — endpoints added or changed, and whether each has a test and a Postman request.
3. **Decisions made** — each decision, who made it (owner or Claude Code), and why.
4. **Open questions** — anything still waiting on the owner, including unanswered items from `docs/project-brief.md` §17.
5. **Test status** — the result of `/preflight` right now.
6. **Environments** — what is running in development and in production, and which commit production is on.
7. **Known problems** — bugs, shortcuts or TODOs left in the code, with file paths.
8. **Next session** — the first three tasks, in order.
9. **Owner actions** — every pending item from `docs/owner-actions.md`, repeated in full.

Then:

- Update `CLAUDE.md` if a command, folder or rule changed this session. Keep it under 200 lines and remove anything that is no longer true.
- Update `docs/api.md` and `docs/owner-actions.md` if they are behind.
- Run `/preflight`. If it is green, commit with the message `docs: session $ARGUMENTS recap`.
- Tell the owner in plain language what was done and what he should do next.

Never include a secret, a key or a full connection string in the recap.
````

---

## 7. Subagents — `.claude/agents/`

- **Why:** a subagent is a separate Claude with its own instructions and a fresh view. These two can only read and search, so they cannot change anything.
- **Because** they did not write the code, they have no reason to assume the code is right.
- **How they run:** Claude Code starts the right one on its own after changing the folders it covers. You can also ask: "Use the security-reviewer subagent to review the latest changes."

| Reviewer | Covers | Example finding |
|---|---|---|
| `trading-reviewer` | `trading/`, `exchange/`, `ai/` | "DO NOT COMMIT: `order_router.py` line 48 sends the order before the daily-loss check" |
| `security-reviewer` | `api/`, `services/`, `config/`, `database/`, `postman/` | "DO NOT COMMIT: `GET /api/v1/trades` has no login check" |

**Path:** `.claude/agents/trading-reviewer.md`

````markdown
---
name: trading-reviewer
description: Read-only reviewer for changes under trading/, exchange/ and ai/. Use proactively after modifying those folders and before committing.
tools: Read, Grep, Glob
model: inherit
---

You review trading code for a small, single-user crypto bot that will trade real money. You did not write this code. Be sceptical and specific. You cannot edit files or run commands.

Read `decisions.yaml`, `.claude/rules/trading-safety.md` and the changed files named in the request, plus whatever they import.

Check each of these and report on every one:

1. **Risk engine bypass** — can any path reach the order router without the risk engine?
2. **Money maths** — any `float` in a price, quantity, fee or balance? Any rounding that ignores the pair's step size?
3. **Fees** — is profit calculated after both sides' fees? Is `commission` read from the real fill?
4. **Limits** — are position cap, daily-loss pause, exchange minimum and rate limits enforced, with values read from `decisions.yaml` and not hard-coded?
5. **Mode safety** — can `shadow` or `testnet` code ever send a mainnet order? Is `LIVE_CONFIRM` enforced? Is `live` refused when `APP_ENV=development`?
6. **Duplicates and retries** — can a timeout or reconnect create a second order?
7. **Failure behaviour** — on a Binance error, a dropped stream, a Claude API error or an exhausted AI budget, does the bot stop opening positions and alert?
8. **Kill switch** — does it stop new orders, cancel open ones and survive a restart?
9. **Secrets** — any key, token or connection string in code, logs or error messages?
10. **Tests** — does each changed rule have tests for the allowed case, the blocked case and the boundary? Do tests avoid the network?

Report format:

- **Verdict:** SAFE TO COMMIT or DO NOT COMMIT.
- **Blocking issues:** file, line, what is wrong, how it could lose money, suggested fix.
- **Non-blocking issues:** same format.
- **Not checked:** anything you could not verify, and why.

If you find nothing, say so plainly and list what you checked.
````

**Path:** `.claude/agents/security-reviewer.md`

````markdown
---
name: security-reviewer
description: Read-only reviewer for changes under api/, services/, config/, database/ and postman/. Use proactively after modifying those folders and before committing.
tools: Read, Grep, Glob
model: inherit
---

You review the web API, login, configuration and database code of a small, single-user trading bot. Its API will eventually be reachable from the internet, and it controls a bot that trades real money. You did not write this code. Be sceptical and specific. You cannot edit files or run commands. Do not open `.env`.

Read `.claude/rules/api.md`, `.claude/rules/secrets.md`, `.claude/rules/environments.md` and the changed files named in the request, plus whatever they import.

Check each of these and report on every one:

1. **Open doors** — can any route other than the two health endpoints be called without a valid access token?
2. **Leaks** — does any response, log line or error message include a secret, a password hash, another token or a full connection string?
3. **Passwords** — are they hashed with Argon2, and never stored, logged or returned in plain form?
4. **Login abuse** — are login and password reset rate limited? Do they answer the same way for a known and an unknown account? Do reset codes expire and work only once?
5. **Tokens** — do access tokens expire? Is the signing secret read from settings and never hard-coded? Can a refresh token be revoked?
6. **Registration** — is it closed once the owner account exists?
7. **Dangerous endpoints** — is there any route that can switch to live trading, change a risk limit, or place an order in production outside the risk engine?
8. **Dev-only routes** — do they return 404 when `APP_ENV=production`?
9. **Environment mix-ups** — can development ever connect to `arbipilot_prod`, or production to a `_dev` or `_test` database? Are the guard rails in `config/environment.py` enforced at startup?
10. **Input** — is every request body validated by a schema? Is all SQL built by the ORM or with bound parameters, never by string formatting?
11. **Network** — does the app listen on `127.0.0.1` outside production? Do database connections require TLS?
12. **Postman and docs** — do the files in `postman/` and `docs/` contain any real token, password or key?

Report format:

- **Verdict:** SAFE TO COMMIT or DO NOT COMMIT.
- **Blocking issues:** file, line, what is wrong, how it could be abused, suggested fix.
- **Non-blocking issues:** same format.
- **Not checked:** anything you could not verify, and why.

If you find nothing, say so plainly and list what you checked.
````

---

## 8. Lines to add to `.gitignore`

```
# secrets
.env
.env.*
*.pem
*.key

# python
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/

# claude code (personal, per machine)
.claude/settings.local.json
CLAUDE.local.md
```

Everything else under `.claude/` is committed. The `postman/` folder is committed too, with empty environment values.

---

## 9. Checks after setup

Run these once, after restarting `claude`. Claude Code performs them and shows the owner each result.

| # | Check | How | Pass when |
|---|---|---|---|
| 1 | Instructions loaded | Run `/memory`, then `/context` | `CLAUDE.md` is listed by `/memory`; `secrets.md` and `environments.md` appear under memory files in `/context` |
| 2 | Permissions loaded | Run `/permissions` | The deny, ask and allow rules from section 4 appear |
| 3 | `.env` is editable | Ask: "Add `PORT=3000` to `.env` if it is missing" | It proposes the edit and applies it after approval |
| 4 | Values are never shown | Ask: "Show me my `.env`" | It lists key names with set or empty, and no values |
| 5 | Production asks first | Ask: "Run `ssh arbipilot uptime`" | An approval prompt appears before anything runs |
| 6 | Skills exist | Type `/` | `preflight`, `new-endpoint`, `deploy`, `deploy-check` and `session-recap` are listed |
| 7 | Reviewers exist | Type `@` | `trading-reviewer` and `security-reviewer` can be selected |
| 8 | Commit hook works | Create `leak-test.yaml` containing `API_KEY: ` followed by 30 letters, stage it, try to commit | The commit is blocked with "possible secret"; then delete the file |
| 9 | Format hook works | Once `ruff` is installed, write a `.py` file with uneven spacing | The file is tidied right after the edit |

---

## 10. Your Claude Code cheat sheet

Start every working day the same way, from the project folder:

```
source .venv/bin/activate
claude
```

Run them in the VS Code terminal, with VS Code opened on the `arbipilot_backend` folder itself, not on its parent folder.

| You want to | Do this | Why |
|---|---|---|
| See the plan before anything is written | Press Shift+Tab until it shows plan mode | Because fixing a plan takes one sentence, and fixing code takes an hour |
| Stop it mid-action | Press Esc | It stops and waits for you |
| Undo its last changes | `/rewind` | Because rewinding is cleaner than piling corrections on top of a mistake |
| Start a new, unrelated task | `/clear` | Because leftover context from the old task confuses the new one |
| Point it at a file | Type `@` and the path, for example `@docs/project-brief.md` | It reads exactly that file |
| See what you still have to do | Ask "What owner actions are pending?" or open `docs/owner-actions.md` | Every manual step is listed there |
| See every endpoint | Open `docs/api.md` | It matches the Postman collection |
| Check the code is healthy | `/preflight` | Before every commit |
| Release to production | `/deploy` | Only after your Postman requests pass in development |
| Verify production | `/deploy-check` | After a deploy or an alert |
| End the session properly | `/session-recap 1` (use the session number) | Because tomorrow's session remembers nothing unless it is written down |

### What an owner action looks like

When Claude Code cannot do something itself, it stops and shows a block like this:

```
OWNER ACTION NEEDED
What:        Create a second Telegram bot for development
Why you:     Only your Telegram account can talk to @BotFather
Steps:       1. Open Telegram and message @BotFather
             2. Send /newbot and name it "ArbiPilot Dev"
             3. Paste the token into .env as TELEGRAM_BOT_TOKEN
You will see: BotFather replies with a token
Then tell me: "done"
```

It then checks that the step worked before continuing.

### Your first message in session 1

Paste this after switching to plan mode:

```
Read OBJECTIVES.md, the context/decisions file, docs/day0-recap.md,
docs/project-brief.md and docs/claude-code-setup.md.

This folder, arbipilot_backend, is the project. The Python environment
(.venv) already exists and requirements.txt is mine; do not recreate them.

Step 1: create the Claude Code setup exactly as docs/claude-code-setup.md
describes, then run its section 9 checks with me.

Step 2: list every owner action you already know I must do, from
docs/project-brief.md section 13, as OWNER ACTION NEEDED blocks.

Step 3: plan the rest of session 1 from docs/project-brief.md section 14,
and ask me the open questions in section 17.

Do not write any file until I approve the plan.
```

---

## 11. Keeping it healthy

| Rule | Why | Example |
|---|---|---|
| Update `CLAUDE.md` in the same commit that changes a command, folder or rule | Because a stale instruction is worse than none | A folder is renamed, and the "Where things live" table is fixed in that commit |
| Delete instructions that are no longer true | Because two rules that disagree get resolved at random | The Caddy line is removed if Caddy is deferred |
| Add a line when Claude Code repeats a mistake | Because that is what `CLAUDE.md` is for | "Use `datetime.now(UTC)`, not `utcnow()`" |
| Turn a procedure into a skill once it has been done twice | Because typed-out steps drift | A `/go-live-checklist` skill before the first live day |
| Review `.claude/settings.local.json` now and then | Because "don't ask again" answers pile up there | An accidental allow rule for `ssh` is removed |
| Never weaken a deny rule, a hook or a reviewer to get past a block | Because the block is the system working | A blocked commit is fixed, not forced |

Claude Code also keeps its own notes between sessions ("auto memory"), stored on your laptop outside the repo. It is on by default and can be viewed or switched off with `/memory`. It is a convenience; the recap files and `CLAUDE.md` remain the record that counts.

---

## 12. Deliberately left out for now

| Not set up | Why |
|---|---|
| Modes that skip permission prompts | Because this project trades money, and the prompts on `ssh`, `aws` and `git push` are how you supervise |
| Connections to outside tools (MCP servers) | Because nothing in the build needs one yet, and each adds another thing with access |
| Sandbox mode | Optional extra isolation; worth revisiting in the pre-live bundle |
| A skill for going live | Written during shadow week, once the promotion rules are final |

---

## Sources

- How Claude remembers your project: `https://code.claude.com/docs/en/memory`
- Configure permissions: `https://code.claude.com/docs/en/permissions`
- Hooks reference: `https://code.claude.com/docs/en/hooks`
- Skills: `https://code.claude.com/docs/en/skills`
- Subagents: `https://code.claude.com/docs/en/sub-agents`
