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
- Branches: `main` is the stable version. Every feature gets its own branch, `feature/<name>`, made from an up-to-date `main`, and is merged back only after its checks pass. There is no `dev` branch.
- The owner makes most commits and every push by hand, following `README.md` §2. When work is ready, tell him which files to add and suggest the commit message. Commit yourself only when he asks; never push.
- When you do commit, run `git add` and `git commit` as two separate commands; the secret hook cannot scan files staged in the same command.
- End every session with `/session-recap`.
- When you learn a project-specific lesson, add one line here. Remove rules that no longer apply. Keep this file under 200 lines.

## Talking to the owner

Manfred is the only user and is not a professional Python or DevOps engineer. Explain in plain language, say why, and give one concrete example. When you run something for him, say what you ran and what it showed. Never assume he will debug by hand.
