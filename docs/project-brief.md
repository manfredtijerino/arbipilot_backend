# ArbiPilot — Project Brief for Claude Code

**Written:** 2026-11-09 (end of Day 0) · **Revised:** 2026-11-12 (v7: repo is `arbipilot_backend`, separate frontend later, one `requirements.txt`) · **Save as:** `docs/project-brief.md` · **Audience:** Claude Code, session 1 onward

---

## 0. How to use this file

**Read these before planning anything, in this order:**

1. `OBJECTIVES.md` — the goals and the trading strategy.
2. The context/decisions file — decisions 1–27 and the `CLAUDE.md` Part 9 engineering rules.
3. `docs/day0-recap.md` — provider status and decisions 28–30.
4. This brief — environments, stack, folder layout, endpoints and the build plan.
5. `docs/claude-code-setup.md` — your own configuration: `CLAUDE.md`, rules, permissions, hooks, skills and the reviewer subagents, with every file ready to create.

**Which file wins when they disagree:**

| Topic | Source of truth |
|---|---|
| Goals, strategy logic, what the AI decides | `OBJECTIVES.md` and the context/decisions file |
| Provider status and values (IPs, key names, fees) | `docs/day0-recap.md` |
| Environments, stack, folder layout, endpoints, startup behaviour | This brief |
| `CLAUDE.md`, rules, permissions, hooks, skills, subagents | `docs/claude-code-setup.md` |
| The corrections in section 16 | This brief (they replace parts of the recap) |

If you find a conflict that this table does not settle, **stop and ask the owner**. Do not pick one silently.

**Start in plan mode.** Present a plan for the session and wait for approval before writing any file. Section 17 lists open questions; ask them during planning.

**How the owner works (decided 2026-11-11):**

- **He supervises; you do the work.** You write all the code, create and edit `.env`, set up the database, configure the server and deploy. He reads your plans, approves the commands that reach production or AWS, and tests with Postman and pgAdmin.
- **If he must do something by hand, you tell him clearly.** Use the OWNER ACTION NEEDED block (section 13) and track it in `docs/owner-actions.md`. Never bury a manual step in a long answer.
- **Nothing runs locally except the app and its tests.** No database and no Docker on his laptop.
- **This repo is the backend only** (decided 2026-11-12). It is named `arbipilot_backend` and lives on his laptop at `Desktop/arbitPilot/arbipilot_backend`. A separate frontend repo will be created beside it once the backend is complete.
- He is not a professional Python or DevOps engineer. Explain in plain language, say *why*, and give a concrete example.

---

## 1. The project, end to end

### What it is

ArbiPilot is a personal, single-user, AI-assisted crypto trading bot. It watches Binance Spot markets 24/7, decides when to trade, enforces strict risk limits, and reports to the owner over Telegram. It runs on one small server in Tokyo.

### How one trade flows through the system

| Step | What happens | Why | Example |
|---|---|---|---|
| 1. Listen | The app holds a live WebSocket stream of Binance market data | Because prices change many times per second and polling would be too slow and hit rate limits | A new best bid/ask for a pair arrives every few milliseconds |
| 2. Record | Raw stream messages are saved | Because recorded data becomes test fixtures, so tests never need the network | One night of stream data replays in a test in seconds |
| 3. Detect | The strategy looks for a setup (defined in `OBJECTIVES.md`) | Because the bot only acts on defined conditions, never on impulse | A setup meets the entry conditions |
| 4. Judge | The AI layer (Claude API) evaluates the setup and returns structured JSON | Because the AI adds judgement on top of fixed rules; its exact role is defined in `OBJECTIVES.md` | `{"decision": "skip", "reason": "..."}` |
| 5. Risk check | The risk engine approves, shrinks, or rejects the order | Because no signal, including the AI's, may bypass the limits in `decisions.yaml` | A $40 order is cut to the $24 cap (8% of $300) |
| 6. Execute | The order goes to one of three places, depending on `TRADING_MODE` | Because the same code path must be provable before real money | shadow: simulated fill · testnet: fake exchange · live: real order |
| 7. Record the fill | Price, quantity, `commission` and `commissionAsset` are stored | Because the scoreboard must use the fees actually charged, not assumed | Fee of 0.00075 × $24 = $0.018, paid in BNB |
| 8. Reconcile | The app compares its own books to the exchange balances | Because a silent mismatch means a bug is losing money | A difference above $0.05 per asset raises an alert |
| 9. Score | Expectancy per trade and drawdown are updated, next to two baselines | Because the bot must beat "do nothing" and "just hold BTC" to be worth running | Compared against `hold_usdt` and `buy_and_hold_btc` |
| 10. Report | Telegram sends alerts; Healthchecks.io gets a ping | Because the owner is not watching a screen, and silence must become an alarm | No ping for 10 minutes sends an alert |

### The three trading modes

| Mode | What it does | Why it exists | Example |
|---|---|---|---|
| `shadow` | Real market data, pretend orders, simulated fills | Because it shows whether the strategy would make money, at zero risk | An order "fills" only if the market trades through its price, after a 150 ms delay |
| `testnet` | Real orders on Binance's fake exchange | Because it proves the plumbing (signing, order types, streams). Fees are 0 there, so it never proves profit | A `LIMIT_MAKER` order is accepted and its fill arrives on the user stream |
| `live` | Real orders with real money | The goal, reached only after promotion criteria are met | Starts small, then scales to $300 |

### Why fees dominate everything

Maker and taker fees are both 0.075% (BNB discount on). A round trip costs 0.15%.

Example: a $24 position pays $0.018 to enter and $0.018 to exit, $0.036 in total. A trade must gain more than 0.15% just to break even. Every calculation of profit must subtract fees, using `Decimal`, never `float`.

---

## 2. Main objectives

| # | Objective | Why | Example |
|---|---|---|---|
| 1 | **Prove positive expectancy per trade in shadow before any real money** | Because the target metric is expectancy per trade, not dollars per day (decisions 19–21) | Promote only after at least 100 shadow trades with the lower 90% confidence bound above 0 |
| 2 | **Protect capital first** | Because the account is small and a few bad trades would end the experiment | Max position 8% of equity; trading pauses after a 2% daily loss |
| 3 | **Trade live on a small base, then scale to $300** | Because the owner wants a live bot, with paper trading only as the test stage | Start small, scale to $300 once it holds up |
| 4 | **Run 24/7 without supervision** | Because the owner is asleep or working for most of the bot's hours | Healthchecks.io alerts if the app goes quiet |
| 5 | **Keep the owner in control from a phone** | Because he must be able to stop it instantly from anywhere | `/kill` in Telegram pauses trading |
| 6 | **Stay cheap and simple** | Because complexity is deferred until there is money to protect (decisions 28–30) | No Sentry, B2 or Tailscale during shadow week |
| 7 | **Be honest in measurement** | Because an optimistic simulator would promote a losing strategy | Shadow fills use the trade-through rule, not touch |

Promotion and demotion rules live in `decisions.yaml` (values in `docs/day0-recap.md` §4). Going live always requires the owner's explicit action.

---

## 3. Environments: development and production

There are two environments. Every feature and every bug fix starts in development and reaches production only after it is tested.

| | Development | Production |
|---|---|---|
| **Purpose** | Build and test safely | The real bot |
| **Where the app runs** | The owner's laptop: `python server.py` | Lightsail server `Ubuntu-1` in Tokyo: Docker service `app` |
| **`APP_ENV`** | `development` | `production` |
| **Address** | `http://localhost:3000` | `127.0.0.1:3000` on the server (private; reached through an SSH tunnel until HTTPS exists) |
| **Database** | `arbipilot_dev` | `arbipilot_prod` |
| **Database user** | `arbipilot_dev` | `arbipilot_prod` |
| **Binance** | Testnet key, plus public market data | Mainnet keys, locked to the server's address |
| **`TRADING_MODE`** | `shadow` or `testnet`. `live` is refused. | `shadow` until promoted, then `live` |
| **Telegram** | Development bot; every message starts with `[DEV]` | `@arbipilot_manfred_bot` |
| **Healthchecks ping** | Off | On |
| **AI budget** | Small daily cap | Full daily cap |
| **`.env`** | The file in the laptop's project folder | `~/arbipilot_backend/.env` on the server |
| **Project folder** | `Desktop/arbitPilot/arbipilot_backend` | `~/arbipilot_backend` |
| **Git branch** | `feature/<name>` branches made from `main` (owner decision 2026-11-12; no `dev` branch) | `main` (released by tag) |

Why two environments:

- **Because** a mistake in development costs nothing. Example: a migration with a bug wipes a column in `arbipilot_dev`, and the production records are untouched.
- **Because** the owner can test every endpoint in Postman against development before any of it reaches the bot that trades.

A third database, `arbipilot_test`, exists only for automated integration tests, which wipe it freely.

### Guard rails the code must enforce

Put these in `config/environment.py` and check them at startup, before anything else:

| Rule | Why | Example |
|---|---|---|
| `development` refuses `TRADING_MODE=live` | Real orders must never come from the laptop | Startup stops with "live mode is not allowed in development" |
| `development` refuses a database name ending in `_prod` | A test must never write to production records | A wrong `POSTGRES_DB` stops the app before it connects |
| `development` refuses to start when mainnet trade keys are set | The laptop should not hold them at all | `BINANCE_API_KEY` must be empty on the laptop |
| `production` refuses a database name ending in `_dev` or `_test` | Production must never record real trades in a test database | Same check, other direction |
| Every development message and log line starts with `[DEV]` | So a development alert is never mistaken for a real one | `[DEV] Shadow fill BTCUSDT ...` |
| Dev-only endpoints return 404 in production | They exist for testing, such as a test order | `POST /api/v1/trading/orders/test` |

### How work moves from development to production

1. **Build** on the laptop, on a feature branch made from an up-to-date `main`. Merge it into `main` once it is tested; `main` is always the stable version.
2. **Test** there: `/preflight` green, integration tests green, and the owner's Postman requests pass against `http://localhost:3000`.
3. **Release** with the `/deploy` skill: merge to `main`, tag, pull on the server, add any new `.env` keys there, run migrations on `arbipilot_prod`, restart `app`.
4. **Verify** with `/deploy-check`.

Never fix anything directly on the server.

---

## 4. Technologies and libraries

### Libraries the app needs

| Library | What it does | Why | Example |
|---|---|---|---|
| `fastapi` | The web framework | Because the backend serves the API on port 3000 | `GET /api/v1/health` |
| `uvicorn[standard]` | Runs FastAPI | Because FastAPI needs a server process | Started from `server.py` |
| `sqlalchemy[asyncio]` | Python-to-database layer | Because Python objects are safer than raw SQL strings | `session.add(Trade(...))` |
| `asyncpg` | PostgreSQL driver | Because it is the async driver SQLAlchemy uses for Postgres | Connects to the managed database over TLS |
| `alembic` | Database migrations | Because schema changes must never wipe existing data | `alembic upgrade head` |
| `httpx` | HTTP client | Because it handles Binance REST calls and the Healthchecks ping | `GET /api/v3/exchangeInfo` |
| `websockets` | WebSocket client | Because Binance market and user data arrive as streams | Subscribes to a pair's book ticker |
| `anthropic` | Official Claude API client | Because it has retries and typed responses built in | Sends a setup, receives JSON |
| `python-telegram-bot` | Telegram bot | Because it is the owner's remote control and alarm | `/kill`, `/status`, alerts, password-reset codes |
| `pydantic-settings` | Loads and validates `.env` | Because a bad value must stop the app at startup, not mid-trade | A missing `JWT_SECRET` stops startup and names the key |
| `pyyaml` | Reads `decisions.yaml` | Because risk rules belong in one readable file | `max_position_pct_equity: 0.08` |
| `pyjwt` | Creates and checks login tokens | Because every endpoint except health requires login | `Authorization: Bearer <token>` |
| `argon2-cffi` | Hashes passwords | Because passwords must never be stored in readable form | The `users` table holds a hash, never the password |

### Libraries for testing and code checks

| Library | What it does | Why |
|---|---|---|
| `pytest` | Test runner | Because tests gate every commit and every deploy |
| `pytest-asyncio` | Async test support | Because most of the code is async |
| `ruff` | Linter and formatter | Because one fast tool keeps style consistent |

### Built into Python (nothing to install)

- `asyncio` — runs the streams, the bot, the trading loop and the web server together in one process.
- `decimal.Decimal` — exact money maths. `0.1 + 0.2` as floats gives `0.30000000000000004`; that error is unacceptable in fee and balance calculations.
- `hmac` / `hashlib` — sign Binance requests (HMAC-SHA-256).
- `secrets` — generates the secrets you create (`JWT_SECRET`, database passwords, reset codes).

### Infrastructure and tools

| Technology | What it does | Why |
|---|---|---|
| Python 3.13 | Language | The owner's laptop has 3.13.7; the Dockerfile uses `python:3.13-slim` so both match |
| Lightsail managed PostgreSQL | The database, for both environments | Nothing runs locally; AWS handles backups and updates |
| Docker + Compose | Runs the app **on the server only** | Repeatable deploys and automatic restart. Not used on the laptop. |
| pgAdmin (owner's laptop) | Lets the owner look at both databases | He wants to see the data himself |
| Postman (owner's laptop) | Lets the owner call every endpoint | He tests each process before it goes to production |
| AWS CLI (owner's laptop) | Lets you manage Lightsail from the terminal | So you can create the database and change the firewall without the owner clicking through the console |
| Caddy | HTTPS in front of the app | Needed only when the API or dashboard is opened to the internet; see open question 4 |

### The `requirements.txt` file

There is **one** requirements file. The owner creates it by hand, with the 16 libraries above, names only. If it is missing or empty when session 1 starts, tell him with an OWNER ACTION NEEDED block (the list is in his `python-commands.md`); do not write it for him unless he asks. There is no `requirements-dev.txt`; the three testing tools are at the bottom of the same file.

| Rule | Why | Example |
|---|---|---|
| Never create a second requirements file | The owner chose one list | The Dockerfile installs the same `requirements.txt`, testing tools included |
| Do not recreate or reorder the file; edit it | It is his file, with his comments | You add `==<version>` to existing lines |
| Pin exact versions in session 1 | So the laptop and the server install the same thing | Check what is installed with `pip list`, confirm each version is current and supports Python 3.13, then pin |
| To add a library: add the line, run `pip install -r requirements.txt`, and tell the owner | `pip install <name>` alone never updates the file, so the server would miss it | "I added `requests` because the health check needs it" |
| Never run `pip freeze > requirements.txt` | It replaces the clean list with every sub-dependency | Use `pip show <name>` to read one version |

Do not rely on remembered version numbers.

---

## 5. Folder and file structure

The structure answers one question fast: *where is the thing I am looking for?*

### Where things live

| Looking for | Go to |
|---|---|
| Where the app starts | `server.py` |
| Every `.env` key and what it means | `config/settings.py` |
| Development vs production rules | `config/environment.py` |
| **Database configuration** (connection) | `config/database.py` |
| **Server configuration** (host, port, app setup) | `config/server.py` |
| Risk limits and promotion rules | `decisions.yaml`, loaded by `config/decisions.py` |
| **Every endpoint** | `api/router.py` (the map), then `api/routes/` |
| What a request or response looks like | `api/schemas/` |
| The tables | `database/models/` |
| The database queries | `database/repositories/` |
| Changes to tables | `database/migrations/` |
| **Functions** for login, users, system status | `services/` |
| **AI configuration** (model, budget, timeout) | `ai/config.py` |
| AI prompts | `ai/prompts.py` |
| **Telegram configuration** | `telegram_bot/config.py` |
| Binance connection settings | `exchange/config.py` |
| Strategy, risk engine, orders | `trading/` |
| One-off commands (set up the database, create the owner) | `scripts/` |
| Postman collection and environments | `postman/` |
| Tests | `tests/`, mirroring the folders above |

### The tree

```
arbipilot_backend/
├── server.py                      # START HERE: startup checks, then port 3000
├── .env                           # all credentials for THIS machine (never committed)
├── decisions.yaml                 # risk limits, promotion rules, fees, AI budget
├── requirements.txt               # every library, one list (created by the owner)
├── pyproject.toml                 # ruff and pytest settings
├── alembic.ini                    # migration tool settings
├── Dockerfile                     # how the production container is built
├── docker-compose.yml             # production only: the `app` service
├── README.md                      # short overview + the owner's commands
├── CLAUDE.md                      # Claude Code's standing instructions
├── OBJECTIVES.md                  # the owner's goals and strategy
│
├── config/                        # ALL CONFIGURATION
│   ├── settings.py                # every .env key, typed and commented
│   ├── environment.py             # development vs production guard rails
│   ├── database.py                # database connection + check
│   ├── server.py                  # host, port, FastAPI app factory, startup checks
│   ├── decisions.py               # loads and validates decisions.yaml
│   └── logging.py                 # log format ([DEV] prefix, no secrets)
│
├── api/                           # EVERYTHING POSTMAN CALLS
│   ├── router.py                  # registers every route: the map of the API
│   ├── dependencies.py            # "must be logged in", "dev only"
│   ├── errors.py                  # the one error shape
│   ├── routes/
│   │   ├── health.py              # /health
│   │   ├── auth.py                # /auth
│   │   ├── users.py               # /users
│   │   ├── integrations.py        # /integrations (Binance, database, Claude, Telegram, server)
│   │   ├── market.py              # /market
│   │   ├── trading.py             # /trading
│   │   ├── data.py                # /trades, /orders, /positions, /signals, /performance
│   │   ├── ai.py                  # /ai
│   │   └── system.py              # /system
│   └── schemas/                   # request and response shapes, one file per route group
│
├── database/                      # TABLES AND QUERIES
│   ├── models/                    # one file per table (user.py, trade.py, order.py, ...)
│   ├── repositories/              # all queries, one file per table
│   └── migrations/                # Alembic: one file per table change
│
├── services/                      # FUNCTIONS behind the non-trading endpoints
│   ├── auth_service.py            # login, tokens, password reset
│   ├── user_service.py            # create and update the owner account
│   ├── integration_service.py     # the connection checks
│   └── system_service.py          # status, config view, recent logs
│
├── ai/                            # AI
│   ├── config.py                  # model, timeout, daily budget
│   ├── client.py                  # Claude client + connection check
│   ├── prompts.py                 # prompt templates
│   ├── schemas.py                 # the JSON the model must return
│   └── budget.py                  # counts tokens and enforces the budget
│
├── telegram_bot/                  # TELEGRAM
│   ├── config.py                  # bot token, owner ID, [DEV] prefix
│   ├── client.py                  # bot setup, owner-only check
│   ├── commands.py                # /kill, /status
│   └── alerts.py                  # sending alerts and reset codes
│
├── exchange/                      # BINANCE
│   ├── config.py                  # URLs and keys per trading mode
│   ├── rest_client.py             # signed and public requests
│   ├── market_stream.py           # live prices
│   ├── user_stream.py             # our own order and fill events
│   ├── filters.py                 # minimum order value, step sizes
│   └── recorder.py                # saves stream data for tests
│
├── trading/                       # THE TRADING LOGIC
│   ├── loop.py                    # the main loop
│   ├── strategy.py                # finds setups
│   ├── risk_engine.py             # approves, shrinks or rejects every order
│   ├── order_router.py            # shadow / testnet / live
│   ├── shadow_fills.py            # honest pretend fills
│   ├── reconciliation.py          # our books vs the exchange
│   ├── scoreboard.py              # expectancy, drawdown, baselines
│   └── kill_switch.py             # pause and resume
│
├── monitoring/
│   └── healthchecks.py            # the dead-man's-switch ping
│
├── scripts/                       # ONE-OFF COMMANDS
│   ├── env_status.py              # lists .env keys as set/empty, never values
│   ├── db_bootstrap.py            # creates the three databases and their users
│   └── create_owner.py            # fallback way to create the owner account
│
├── postman/                       # FOR THE OWNER'S TESTING
│   ├── arbipilot.postman_collection.json
│   ├── development.postman_environment.json
│   └── production.postman_environment.json
│
├── tests/                         # mirrors the folders above
│   ├── api/  services/  trading/  exchange/  ai/  database/
│   └── fixtures/                  # recorded market data
│
├── docs/
│   ├── project-brief.md           # this file
│   ├── claude-code-setup.md
│   ├── day0-recap.md
│   ├── api.md                     # the endpoint table, kept in step with the code
│   ├── owner-actions.md           # what the owner must do: pending and done
│   ├── deploys.md                 # one line per production release
│   └── session-N-recap.md
│
└── .claude/                       # Claude Code's own configuration
```

### Rules for the structure

| Rule | Why | Example |
|---|---|---|
| Each folder has one job, named in its `README.md` | So nobody has to guess where new code goes | `database/README.md`: "Tables, queries and migrations. No business logic." |
| Each topic folder has a `config.py` | So the settings for AI, Telegram and Binance are always the first file in their folder | `ai/config.py` holds the model name and budget |
| All `.env` reading happens in `config/settings.py` | So there is exactly one list of keys | `ai/config.py` reads from settings, never from the environment |
| Routes are thin; functions live elsewhere | So Postman-facing code and business logic stay apart | `api/routes/auth.py` calls `services/auth_service.login()` |
| SQL lives only in `database/repositories/` | So a table change touches one place | No query inside a route or a strategy |
| `tests/` mirrors the code | So the test for a file is easy to find | `tests/trading/test_risk_engine.py` |
| `server.py` only wires things together | So the entry point stays readable | No business logic in it |
| Lowercase paths everywhere | The laptop ignores case; the Linux server does not | The parent folder on the laptop is `arbitPilot`; never write that name into code or paths |
| No frontend code in this repo | The frontend is its own repo | No HTML, templates or assets here; the API is the only door |

The Telegram folder must be `telegram_bot`, never `telegram`: the library is imported as `telegram`, and a folder with that name would hide it.

`.venv/` already exists on the laptop (created by the owner on 2026-11-12, Python 3.13.7, pip 26.3), and `requirements.txt` is his to create. Do not recreate or delete either. The project folder must not be moved or renamed, because that breaks `.venv/`.

---

## 6. Startup contract for `server.py`

Running `python server.py` must print exactly these status lines, in this order.

**Every line must be true when it is printed.** Check the environment guard rails first, then run all four checks and collect the results, then print the lines. Never print "Running on port 3000" and then exit because a later check failed.

Success:

```
✔ Running on port 3000
✔ Database connected successfully (arbipilot_dev)
✔ Server connected successfully
✔ Claude API connected successfully
Environment: DEVELOPMENT
Mode: SHADOW
```

Failure replaces the line with an error and the reason:

```
✖ Database connection failed: could not reach the managed database (host unreachable)
```

| Line | What it must actually test | If it fails |
|---|---|---|
| Running on port 3000 | The port from `PORT` is bound and accepting connections | Print the error and exit with code 1 |
| Database | `SELECT 1` on the managed database, over TLS; print the database name | Print the error and exit with code 1 (the app cannot record trades) |
| Server | Binance reachable: fetch server time and check clock drift is within tolerance (see open question 3) | Print the error and exit with code 1 |
| Claude API | Key is valid and `ANTHROPIC_MODEL` is in the model list; listing models costs no tokens | Print the error, **start anyway with new entries disabled**, and send a Telegram alert |

Rules:

- A guard-rail failure (section 3) prints one clear line and exits before any connection is attempted.
- When any fatal check fails, print all four results (so the owner sees everything that is wrong at once), then exit with code 1.
- In production the `app` service uses `restart: unless-stopped`, so an outage at startup becomes a retry loop. Back off between attempts and send **one** Telegram alert per outage, not one per retry.
- Error messages must never contain a secret, a password or a full connection string.
- In `live` mode also print the confirmation date.
- Also send the environment, mode and check results to Telegram at startup, so the owner always knows what is running.
- In development the app listens on `127.0.0.1` only.

---

## 7. Configuration, `.env` and the databases

### `.env`: one file per machine

There is one `.env` on the laptop (development values) and one on the server (production values). There is no `.env.example` or other template. **You create and edit both.** The list of keys is the `Settings` class in `config/settings.py`: every field has a type and a comment, and a missing or invalid key stops the app at startup with a message naming the key, never its value.

| Key | Laptop (development) | Server (production) | Who provides the value |
|---|---|---|---|
| `APP_ENV` | `development` | `production` | You |
| `PORT` | `3000` | `3000` | You |
| `TRADING_MODE` | `shadow` | `shadow` (later `live`) | You; `live` only on the owner's instruction |
| `LIVE_CONFIRM` | empty | empty until go-live | The owner's instruction |
| `POSTGRES_HOST` | Public endpoint of the managed database | Private endpoint of the managed database | You, from AWS |
| `POSTGRES_PORT` | `5432` | `5432` | You |
| `POSTGRES_DB` | `arbipilot_dev` | `arbipilot_prod` | You |
| `POSTGRES_USER` | `arbipilot_dev` | `arbipilot_prod` | You |
| `POSTGRES_PASSWORD` | Development user's password | Production user's password | You generate it |
| `POSTGRES_SSLMODE` | `require` | `require` | You |
| `POSTGRES_TEST_DB` | `arbipilot_test` | not set | You |
| `PGADMIN_READONLY_PASSWORD` | Password of the read-only production user, for the owner's pgAdmin | not set | You generate it |
| `JWT_SECRET` | Generated | Generated, different | You generate it |
| `BINANCE_TESTNET_KEY` / `_SECRET` | Set | Set | **The owner** |
| `BINANCE_READ_KEY` / `_SECRET` | empty | Set | **The owner** |
| `BINANCE_API_KEY` / `_SECRET` (trade key) | **must be empty** | Set | **The owner** |
| `BINANCE_BASE_URL`, `BINANCE_WS_URL` | As in the recap | As in the recap | You |
| `FEE_MAKER`, `FEE_TAKER` | `0.00075` | `0.00075` | You |
| `ANTHROPIC_API_KEY` | Set | Set | **The owner** |
| `ANTHROPIC_MODEL` | Chosen in session 1 | Same | You, with the owner |
| `TELEGRAM_BOT_TOKEN` | Development bot | Production bot | **The owner** |
| `TELEGRAM_OWNER_ID` | Set | Set | **The owner** |
| `HEALTHCHECKS_PING_URL` | empty | Set | **The owner** |
| `EXPECTED_PUBLIC_IP` | empty | `13.193.72.121` | You |
| `FRONTEND_ORIGINS` | empty for now | empty for now | You, when the frontend exists |

Rules:

- **Values marked "The owner"** are in his password manager. Do not ask him to paste them into the chat. Show an OWNER ACTION NEEDED block naming the key, then verify with `scripts/env_status.py` and a live connection check.
- **Never copy one machine's `.env` to the other.** They differ on purpose.
- **After you generate a secret,** ask the owner to copy it from `.env` into his password manager.
- **Never show a value** in chat, output, logs, docs or Postman files. `scripts/env_status.py` prints key names with "set" or "empty" only; write it in session 1 and use it whenever that is enough.
- **`live` refuses to start** unless `LIVE_CONFIRM` holds today's date, and is refused outright in development.
- **`testnet` swaps both Binance URLs** to the testnet hosts and uses the testnet key.
- **The model name is configuration, not code.** Check the current Anthropic model list and pick the smallest model that meets the task.
- **The AI has a spending budget.** Add an `ai:` block to `decisions.yaml` with daily call and cost limits per environment (values: open question 6). Count tokens from every response, alert at 80%, and stop calling the AI for the rest of the UTC day at 100%.

### The databases

PostgreSQL runs on **one Lightsail managed database** in Tokyo, the same region as the server. Nothing is installed on the laptop or in Docker.

| Database | Used by | User | Can be wiped? |
|---|---|---|---|
| `arbipilot_dev` | The development app on the laptop | `arbipilot_dev` | Yes, with the owner's approval |
| `arbipilot_test` | Automated integration tests only | `arbipilot_dev` | Yes, tests do it freely |
| `arbipilot_prod` | The production app on the server | `arbipilot_prod` | Never |

A fourth user, `arbipilot_readonly`, can only read `arbipilot_prod`. The owner uses it in pgAdmin, so he can look at production data without any chance of changing it. Each user can connect only to its own databases.

**Why one managed database for both (owner decision, 2026-11-11):**

- **Because** it costs about $15 a month, and two would put the AWS bill above the $40 alarm.
- **Because** AWS handles backups: automatic daily backups kept for 7 days, with restore to any point in that window.
- **The trade-off:** development and production share one machine. Separate users and databases keep the data apart, but a runaway development query could slow production. At this size that risk is small. Tell the owner if it ever shows up.

**How it is created:**

| Step | Who | What | Why |
|---|---|---|---|
| 1 | Owner (one time) | Gives you AWS access (open question 9) | Only he can log in to the AWS root account |
| 2 | You | Check which PostgreSQL versions and plans Lightsail offers now, then create the managed database: Tokyo, same zone as the server, the smallest standard plan, the newest supported PostgreSQL | Do not rely on memory for AWS options or prices; show the owner the monthly price before creating it |
| 3 | You | Turn on public mode (open question 5) and fetch the two endpoints | The laptop and pgAdmin are outside AWS and need the public endpoint; the server uses the private one |
| 4 | You | Write and run `scripts/db_bootstrap.py`: create the three databases and three users with generated passwords, remove default public access, and grant each user only its own databases | So no user can reach a database it should not |
| 5 | You | Write the development values into the laptop's `.env` | |
| 6 | You | Run `alembic upgrade head` on `arbipilot_dev` once migrations exist | Tables are created by migrations, never by hand |
| 7 | Owner | Saves the generated passwords in his password manager and sets up pgAdmin (below) | You tell him with an OWNER ACTION NEEDED block |
| 8 | You, at first deploy | Write the production values into the server's `.env` and run the migrations on `arbipilot_prod` | Through `/deploy`, with approval |

`db_bootstrap.py` must be safe to run twice, and must fetch the master password from AWS at run time, never store it.

**pgAdmin settings for the owner** (give him these in an OWNER ACTION NEEDED block once the database exists):

| Field | Development | Production |
|---|---|---|
| Name | `ArbiPilot DEV` | `ArbiPilot PROD (read-only)` |
| Host | The public endpoint | The same public endpoint |
| Port | `5432` | `5432` |
| Maintenance database | `arbipilot_dev` | `arbipilot_prod` |
| Username | `arbipilot_dev` | `arbipilot_readonly` |
| Password | `POSTGRES_PASSWORD` in the laptop's `.env` | `PGADMIN_READONLY_PASSWORD` in the laptop's `.env` |
| SSL mode | Require | Require |
| Suggested colour | Green | Red |

Rules:

- **Tables change only through migrations.** The owner should look in pgAdmin, not edit there; a hand-made change breaks the next migration.
- **Every migration runs in development first** and reaches production only through `/deploy`.
- **Before a migration that drops or changes a column in production,** take a manual snapshot and tell the owner its name.
- **Never delete the managed database, a database or a snapshot.**
- **The laptop is far from Tokyo,** so each development query takes a noticeable fraction of a second. Batch queries; never loop one query per row.

---

## 8. API endpoints and Postman

All endpoints are under `/api/v1`. Everything requires login except the two health endpoints. The live table is `docs/api.md`; create it in session 1 from this list and keep it in step with the code.

### Health (no login)

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Is the app alive? Returns environment, trading mode and version. |
| GET | `/health/ready` | Is everything connected? Returns ok or failed for the database, Binance, Claude and Telegram. |

### Login and users

| Method | Path | What it does |
|---|---|---|
| POST | `/auth/register` | Creates the owner account (email and password). Works only while no account exists. |
| POST | `/auth/login` | Checks email and password; returns an access token and a refresh token. |
| POST | `/auth/refresh` | Swaps a refresh token for a new access token. |
| POST | `/auth/logout` | Cancels the refresh token. |
| POST | `/auth/password/forgot` | Sends a one-time reset code to the owner's Telegram. |
| POST | `/auth/password/reset` | Sets a new password using the reset code. |
| POST | `/auth/password/change` | Changes the password while logged in. |
| GET | `/users/me` | Returns the logged-in user's profile. |
| PATCH | `/users/me` | Updates the profile. |

### Integration checks

| Method | Path | What it does |
|---|---|---|
| GET | `/integrations/binance` | Tests the Binance connection: reachable, clock difference, keys valid, trading allowed, withdrawals disabled, fee rates. |
| GET | `/integrations/binance/balances` | Returns the Spot balances for USDT and BNB. |
| GET | `/integrations/database` | Tests the database: name, version, latest migration applied. |
| GET | `/integrations/claude` | Tests the Claude API key and model; returns today's usage against the budget. |
| POST | `/integrations/telegram/test` | Sends a test message to the owner's Telegram. |
| POST | `/integrations/healthchecks/test` | Sends a test ping to Healthchecks.io. |
| GET | `/integrations/server` | Reports on the machine the app runs on: public address (and whether it matches the one Binance expects), uptime, memory, disk, clock sync. In production this is the Lightsail server. |

### Market data

| Method | Path | What it does |
|---|---|---|
| GET | `/market/symbols` | Lists the pairs the bot watches, with each pair's minimum order value. |
| GET | `/market/ticker/{symbol}` | Returns the latest price for one pair. |
| GET | `/market/stream/status` | Shows whether the live price stream is connected and how old the last message is. |

### Trading control

| Method | Path | What it does |
|---|---|---|
| GET | `/trading/status` | Environment, mode, running or paused (and why), open positions, today's profit or loss. |
| GET | `/trading/risk` | The current limits from `decisions.yaml` and how much of each is used today. |
| POST | `/trading/kill` | Pauses trading and cancels open orders. |
| POST | `/trading/resume` | Resumes trading after a pause. |
| POST | `/trading/orders/test` | **Development only.** Sends one test order through the full path (risk engine, router, fill) in shadow or testnet. |

### Data

| Method | Path | What it does |
|---|---|---|
| GET | `/trades` | Lists trades, newest first, with filters for pair, date and mode. |
| GET | `/trades/{id}` | One trade in full: entry, exit, fees, AI verdict, risk decision. |
| GET | `/orders` | Lists orders and their status. |
| GET | `/positions` | Lists open positions. |
| GET | `/signals` | Lists setups the strategy found and what was decided about each. |
| GET | `/performance/summary` | Expectancy per trade, win rate, drawdown, and the comparison with the two baselines. |
| GET | `/performance/daily` | Profit or loss per day. |
| GET | `/reconciliation/latest` | The latest comparison between our records and the exchange. |

### AI

| Method | Path | What it does |
|---|---|---|
| GET | `/ai/usage` | Calls, tokens and cost today and this month, against the budget. |
| GET | `/ai/decisions` | Recent AI verdicts with their reasons. |
| POST | `/ai/evaluate` | **Development only.** Sends a sample setup to the AI and returns its verdict. Costs tokens. |

### System

| Method | Path | What it does |
|---|---|---|
| GET | `/system/config` | The non-secret configuration in use: environment, mode, limits, model. Never a secret. |
| GET | `/system/logs` | Recent log lines, filtered by level. |
| GET | `/system/events` | Recent alerts and important events. |

### The frontend comes later

The frontend will be a separate repo (working name `arbipilot_frontend`), started once this backend is complete. Build the backend so that step is easy:

| Rule | Why | Example |
|---|---|---|
| The API is the only way in | So the frontend needs nothing but endpoints | The dashboard reads `GET /performance/summary`; it never touches the database |
| `docs/api.md` is the contract | So the frontend can be built from the document | Every field of every response is described there |
| Add fields, never rename or remove them without telling the owner | So a backend change cannot silently break the frontend | A new `fee_asset` field is added; `fee` keeps its name |
| Browser access is limited to the addresses in `FRONTEND_ORIGINS` | So only the owner's frontend can call the API from a browser | Empty until the frontend exists; never `*` |
| The frontend's development server must not use port 3000 or 3001 | 3000 is this backend, and 3001 is the tunnel to production | Use another port, such as 5173 |

The "dashboard" in the deferred pre-live bundle is that frontend project.

That is 40 endpoints. Three things are deliberately missing:

- **No endpoint switches to live trading or changes a risk limit.** Those stay as deliberate actions outside the API.
- **No endpoint places an order in production.** Only the trading loop does, through the risk engine.
- **No endpoint returns a secret.**

### How login works

| Design choice | Why | Example |
|---|---|---|
| One owner account; registration closes after it exists | The bot is single-user | A second `POST /auth/register` returns an error |
| Passwords hashed with Argon2 | A stolen database must not reveal the password | The `users` table stores only a hash |
| Short-lived access token (30 minutes) plus a refresh token (7 days) | A leaked access token soon stops working | Postman refreshes automatically or you log in again |
| Reset code sent by Telegram, valid 10 minutes, usable once | There is no email provider, and Telegram already reaches only the owner | "Your ArbiPilot reset code is 493 201" |
| Login and reset are rate limited | To stop password guessing | Five wrong passwords lock login for 15 minutes |
| Same answer whether or not the email exists | So nobody can discover the owner's email | "If the account exists, a code was sent" |

Two-factor login (TOTP) stays in the pre-live bundle with the dashboard.

### Postman

| Item | Detail |
|---|---|
| Collection | `postman/arbipilot.postman_collection.json`, one folder per group above, in the same order |
| Development environment | `base_url = http://localhost:3000/api/v1` |
| Production environment | `base_url = http://localhost:3001/api/v1`, through an SSH tunnel: `ssh -N -L 3001:127.0.0.1:3000 arbipilot` |
| Variables | `base_url`, `email`, `password`, `access_token`, `refresh_token`. The files in the repo hold empty values; the owner types his email and password into Postman only. |
| Login | The login request saves `access_token` into the environment by script; every other request sends `Authorization: Bearer {{access_token}}` |
| Each request | Has an example body, a saved example response and a test that checks the status code |
| Updates | You update the collection in the same commit as the endpoint, then tell the owner to re-import it |

**Why the tunnel for production:** the production API listens only inside the server until HTTPS and two-factor login exist. The tunnel lets the owner's Postman reach it without opening it to the internet.

Use the `/new-endpoint` skill for every endpoint, so its test, its Postman request and its row in `docs/api.md` are created together.

---

## 9. Providers and tools

| Provider | What it does | Why | Example |
|---|---|---|---|
| **AWS Lightsail server** | Runs production: `Ubuntu-1`, Tokyo `ap-northeast-1a`, Ubuntu 24.04 LTS, 2 GB RAM + 2 GB swap, 2 vCPU, 60 GB | Because it is a fixed-price ($12/month) server, and Tokyo keeps network latency to Binance low | The `app` container runs there. Daily snapshots at 14:00 UTC, 7 kept. Never run `do-release-upgrade`. |
| **AWS Lightsail managed database** | PostgreSQL for both environments (new, 2026-11-11) | Because nothing runs locally and AWS handles backups | About $15/month for the smallest standard plan as of early 2026; confirm the current price before creating it |
| **AWS account** | Billing and security wrapper | Because the root account needs MFA and a spending alarm | Server plus database is about $27/month, under the $40 alarm. A support case for a 4 GB server plan is open; if granted, tell the owner the new total before upgrading. |
| **AWS CLI + a limited IAM user** | Lets you manage Lightsail from the laptop's terminal | Because the owner wants you to configure Lightsail, and the root login is his alone | `aws lightsail get-relational-databases`. Every `aws` command asks for approval; delete commands are denied. |
| **Static IP + sslip.io** | Fixed address `13.193.72.121`; hostname `13-193-72-121.sslip.io` | Because Binance keys are locked to one IP, and sslip.io gives a hostname for HTTPS without buying a domain | Used when HTTPS is added |
| **SSH** | `ssh arbipilot` from the laptop, key-only (Ed25519), user `ubuntu` | Because it is how you deploy and how the owner's Postman reaches production | Every `ssh` command asks for approval |
| **Binance (mainnet)** | The exchange. Key `arbipilot-read` (read only) and key `arbipilot-trade` (read + spot trading, **no withdrawals**), both IP-locked | Because separate keys limit damage, and no key can move money out | Production only. They cannot work from the laptop. |
| **Binance Spot testnet** | A fake exchange. Key `arbipilot-testnet` | Because it lets development test real order plumbing without money | Fees are 0 and it resets about monthly without notice, so never use it to judge profit |
| **GitHub** | Private repo `arbipilot_backend` (new on 2026-11-12; the older empty `arbipilot` repo is unused) | Because it is the backup, the history, and how code reaches the server | Feature branches for work, `main` as the stable version and for releases; the owner commits and pushes by hand. Run `git status` and `git remote -v` first to confirm the folder is linked; the recap's `github.com-personal` alias applied to the old repo and may not be set here. |
| **Telegram** | Production bot `@arbipilot_manfred_bot`, plus a development bot (open question 10) | Because it puts alerts, the kill switch and reset codes on the owner's phone | Only messages from `TELEGRAM_OWNER_ID` are obeyed |
| **Anthropic** | Claude API, key `arbipilot` | Because it powers the AI layer | No payment method is on file, on purpose: when the monthly credit runs out, calls fail instead of billing. Both environments spend the same credit. |
| **Healthchecks.io** | Dead-man's switch: check `arbipilot-worker`, period 5 min, grace 5 min | Because it is the only thing that turns a dead app into an alert | Production only. The check keeps its old name even though the service is now `app`. |
| **pgAdmin** | The owner's window into both databases | Because he wants to see the data himself | Development with full access, production read-only |
| **Postman** | The owner's way to test every endpoint | Because he tests each process before it goes to production | One collection, two environments |

**Deferred to pre-live (do not build yet):** Backblaze B2 backups · Sentry · Tailscale · the frontend (dashboard) in its own repo, with two-factor login · Cloudflare Access · HTTPS for the API.
**Rejected:** MongoDB (decision 27) · Lightsail `.pem` files (decision 26) · a local database · Docker on the laptop.

---

## 10. Claude Code setup

Your own configuration is specified in full in **`docs/claude-code-setup.md`**, with the exact content of every file. Create it as the first step of session 1, before any project code, then run the checks in its section 9 with the owner.

| Piece | Path | Purpose |
|---|---|---|
| Standing instructions | `CLAUDE.md` | Loaded every session; environments, commands, "where things live", hard rules |
| Topic rules | `.claude/rules/` | Secrets and environments (always loaded); API, database, trading safety, AI layer, Python style, testing (loaded by path) |
| Permissions | `.claude/settings.json` | Ask before `ssh`, `scp`, `aws`, `git push`; deny deleting AWS resources and printing `.env`; allow tests, lint and development migrations |
| Hooks | `.claude/hooks/` | Block a commit that contains a secret; format Python files after each edit |
| Skills | `.claude/skills/` | `/preflight`, `/new-endpoint`, `/deploy`, `/deploy-check`, `/session-recap` |
| Reviewers | `.claude/agents/` | `trading-reviewer` and `security-reviewer`, both read-only |

---

## 11. Hard rules (never break these)

**Secrets**

1. Secrets live only in the two `.env` files. You may read and edit them. Never show a secret value in chat, command output, logs, docs, Postman files or a commit.
2. Never commit `.env`. Never create `.env.example` or any other copy. Never copy one machine's `.env` to the other.
3. Never put mainnet Binance keys or production database credentials in the laptop's `.env`.
4. Never ask the owner to paste a secret into the chat. Name the `.env` key for him to fill.
5. If a secret is ever exposed, tell the owner at once and help him rotate it.

**Money and risk**

6. Never set `TRADING_MODE=live` or `LIVE_CONFIRM` unless the owner tells you to in that session, in his own words. Never in development.
7. Never loosen a limit in `decisions.yaml` (position size, loss pause, promotion criteria) without the owner's explicit approval.
8. Never let any code path place an order without passing through the risk engine.
9. Never place real or testnet orders from tests.
10. Never add withdrawal, transfer, margin or futures functionality. Spot trading only.
11. Never add an endpoint that switches to live trading, changes a risk limit or places a production order.

**Environments and infrastructure**

12. Never let the development app connect to `arbipilot_prod`, or tests touch anything but `arbipilot_test`.
13. Production changes only through `/deploy`. Never edit code on the server.
14. Every `ssh`, `scp` and `aws` command waits for the owner's approval, with one sentence saying what it does.
15. Never delete the managed database, a database, a snapshot, the server or `.venv/`. Never run destructive SQL on `arbipilot_prod`.
16. Never run `do-release-upgrade` on the server. Never open port 3000 or the database to the internet beyond what open questions 4 and 5 decide.
17. Never build deferred items (B2, Sentry, Tailscale, dashboard, Cloudflare) before the owner starts the pre-live bundle.

**The owner**

18. Never leave a manual step unannounced. Every one gets an OWNER ACTION NEEDED block and a line in `docs/owner-actions.md`.
19. Never assume a manual step was done. Verify it, then mark it done.

---

## 12. Engineering rules for trading code

| Rule | Why | Example |
|---|---|---|
| Use `Decimal` for every price, quantity, fee and balance | Float rounding corrupts money maths | Parse Binance's string numbers straight into `Decimal` |
| All timestamps in UTC | Mixed time zones corrupt daily-loss and drawdown calculations | The "day" for the 2% loss pause is a UTC day |
| Fees are 0.00075 per side, maker and taker | BNB discount is on | `LIMIT_MAKER` is used for honest shadow fills, not fee savings |
| Read `commission` and `commissionAsset` on every fill; alarm on mismatch | If BNB runs out, fees silently rise to 0.1% | Expected 0.00075, charged 0.001 → Telegram alert |
| Makers use `LIMIT_MAKER` | It is rejected instead of crossing the spread, which keeps simulation and reality aligned | An order that would take liquidity is refused by the exchange |
| Shadow fills use trade-through with a 150 ms delay | "Touch" fills overstate results | A buy at 100.00 fills only after a trade prints below 100.00 |
| Read minimum order value and step sizes from `exchangeInfo` at startup; skip and log any order below the minimum | Minimums differ per pair and change | An order under the pair's minimum is never sent |
| Enforce order-rate limits inside the risk engine | Exceeding Binance limits gets the IP banned | A burst of signals is throttled, not sent |
| Every order carries a unique client order ID and is safe to retry | A timeout must not create a duplicate order | Retrying with the same ID returns the original order |
| Reconcile against the exchange; tolerance $0.05 per asset | A drift means a bug or a missed fill | Drift above tolerance pauses trading and alerts |
| Expect WebSocket drops (at least every 24 h) and reconnect with backoff | Binance closes streams by design | After reconnect, re-sync state from REST before trading |
| **Verify the current user-data-stream method in Binance's docs before coding it** | The recap assumes listen keys with a 30-minute keepalive; Binance has been changing this API | Implement whatever the current Spot docs specify |
| Assume the server clock is synced (chrony); still check drift at startup | Signed requests fail when the clock is off | The "Server connected" check compares local and Binance time |
| The kill switch stops new orders and cancels open ones, and persists across restarts | A restart must not quietly resume trading | After `/kill`, only an explicit resume re-enables entries |
| When the Claude API fails or the credit is exhausted: no new entries, manage existing positions by rules, alert once | The AI is a judge, not a dependency for safety | A 4xx/5xx from Anthropic never crashes the loop |
| Enforce the daily AI budget from `decisions.yaml` (calls and cost) | The monthly credit is finite and has no top-up | At 80% of the day's budget an alert is sent; at 100% the AI is not called again until the next UTC day |
| Log structured lines with no secrets | The owner reads logs with `docker compose logs -f` | One line per decision: setup, AI verdict, risk result |

---

## 13. Who does what

### You do

Everything that can be done from the laptop's terminal: writing code and tests, creating and editing `.env`, creating and configuring the managed database, running migrations, building the Postman collection, deploying over SSH, configuring the server, and checking that it all works.

### The owner approves

Every command that reaches production or AWS (`ssh`, `scp`, `aws`), every `git push`, every deploy, any change to a risk limit, and the switch to live trading.

### The owner must do by hand

These need his accounts, his devices or his secrets. Announce each one with the block below when its time comes, and keep `docs/owner-actions.md` current.

| # | Action | Why only he can | When |
|---|---|---|---|
| 1 | Give you AWS access (a limited IAM user and `aws configure`), or create the database in the console himself | The AWS root login is his | Day 1 |
| 2 | Fill the keys only he holds into the laptop's `.env`: Binance testnet key, Anthropic key, Telegram token and owner ID | They are in his password manager | Day 1 |
| 3 | Create a development Telegram bot with @BotFather | Only his Telegram account can | Day 1 |
| 4 | Install pgAdmin and add the two connections | It is an app on his laptop | Day 1, after the database exists |
| 5 | Install Postman and import the collection and both environments | It is an app on his laptop | Day 1, and after each new endpoint |
| 6 | Copy each secret you generate from `.env` into his password manager | So nothing is lost if the laptop is | Each time you generate one |
| 7 | Choose his email and password and call `POST /auth/register` from Postman | The password must be known only to him | Day 2 |
| 8 | Run his Postman requests against development and say whether they pass | It is his test of the system | Before every deploy |
| 9 | Fill the production-only keys into the server's `.env`: Binance read and trade keys, production Telegram token, Healthchecks URL | They are in his password manager | First deploy |
| 10 | Add the server's deploy key to GitHub, if you cannot do it with the `gh` tool | It needs his GitHub login | First deploy |
| 11 | Open the SSH tunnel when he wants Postman to reach production | It runs in his terminal | After the first deploy |
| 12 | Confirm about $300 USDT and $10 BNB are in the Binance **Spot** wallet | Only he can see and move his funds | Before going live |
| 13 | Tell you to go live | It is his money | After the promotion criteria are met |

### The notification block

```
OWNER ACTION NEEDED
What:        <one sentence>
Why you:     <why Claude Code cannot do it>
Steps:       1. ...  2. ...
You will see: <what success looks like>
Then tell me: "done"
```

Rules: stop and wait after showing it; give exact clicks and exact text to type; verify the result yourself before continuing; repeat every pending action in each session recap.

---

## 14. Build plan

The scope grew on 2026-11-11: login, a 40-endpoint API, a managed database and two environments were added. The plan is now four build days, not three. Tell the owner if a day runs over; do not cut tests to keep the schedule.

| Day | Scope | The owner can test, in Postman |
|---|---|---|
| **Day 1** | Claude Code setup and its checks · owner actions 1–5 · managed database and `db_bootstrap.py` · repo foundation and folder structure · `config/` (settings, environment guard rails, database, server) · `server.py` with the startup contract · health endpoints · `decisions.yaml` · Postman collection started | `GET /health`, `GET /health/ready` |
| **Day 2** | Tables and first migrations · login and users · integration checks · Binance client and filters · market endpoints · stream recorder | Register, login, reset password, every `/integrations` check, `/market` |
| **Day 3** | Strategy · risk engine · shadow fills · order router · AI layer and budget · trading, data, AI and system endpoints | `/trading`, a test order, `/trades`, `/ai`, `/system` |
| **Day 4** | Testnet run · reconciliation · scoreboard · first `/deploy` to production in shadow mode · `/deploy-check` | The same collection against production through the tunnel |
| **Shadow week** | Collect at least 100 shadow trades · then the pre-live bundle (dashboard with two-factor login, HTTPS, Tailscale, B2, Sentry, private database) | `/performance/summary` |
| **Live** | Only after the promotion criteria are met and the owner tells you to switch | |

The milestone numbering comes from the context/decisions file; map this table onto it during planning and show the owner the mapping.

---

## 15. Commands

You run these. The owner approves the ones marked ⚠. Keep this table and `README.md` in step with the code.

**Development (laptop)**

| Purpose | Command |
|---|---|
| Activate the Python environment | `source .venv/bin/activate` |
| Install libraries | `pip install -r requirements.txt` |
| Run the backend | `python server.py` |
| See which `.env` keys are set (no values) | `python scripts/env_status.py` |
| Create or update the tables | `alembic upgrade head` |
| Unit tests | `pytest` |
| Integration tests (use `arbipilot_test`) | `pytest -m integration` |

**Production (server)**

| Purpose | Command |
|---|---|
| ⚠ Release | `/deploy` in Claude Code |
| ⚠ Verify | `/deploy-check` in Claude Code |
| ⚠ Is it running? | `ssh arbipilot "cd ~/arbipilot_backend && docker compose ps"` |
| ⚠ Watch the logs | `ssh arbipilot "cd ~/arbipilot_backend && docker compose logs --tail 200 app"` |
| ⚠ Full stop | `ssh arbipilot "cd ~/arbipilot_backend && docker compose down"` |
| ⚠ Start again | `ssh arbipilot "cd ~/arbipilot_backend && docker compose up -d"` |

**The owner's own**

| Purpose | How |
|---|---|
| Pause trading from anywhere | `/kill` in Telegram, or `POST /trading/kill` in Postman |
| Reach production from Postman | `ssh -N -L 3001:127.0.0.1:3000 arbipilot` in a terminal, then use the Production environment |
| Look at the data | pgAdmin: `ArbiPilot DEV` or `ArbiPilot PROD (read-only)` |
| Go live | Tell Claude Code: "go live". It sets `TRADING_MODE=live` and `LIVE_CONFIRM` on the server and redeploys. |
| Server unreachable | Binance phone app → Orders → Cancel all |

---

## 16. Corrections to `docs/day0-recap.md` (owner decisions through 2026-11-11)

| Recap says | Correct | Why |
|---|---|---|
| A `db` container (Postgres 16) with a Docker volume | One Lightsail managed PostgreSQL holding `arbipilot_dev`, `arbipilot_test` and `arbipilot_prod` | Nothing runs locally; AWS handles backups |
| One environment | Development (laptop) and production (server), with guard rails | Features and fixes are tested before they reach the real bot |
| Docker Compose used on the laptop too | Docker runs on the server only | Nothing local except the app and its tests |
| The owner pastes values into `.env`; Claude Code never reads it | Claude Code creates, reads and edits `.env`, and never shows a value | The owner supervises; Claude Code operates |
| The cheat sheet is "the only commands the human runs" | Claude Code runs the commands; the owner approves the production ones | Same reason |
| One `.env`, copied to the server | One `.env` per machine with different values, never copied; no template file | Development and production must not share credentials |
| No web server during shadow | FastAPI on port 3000 with a 40-endpoint API and login | The owner tests every process in Postman |
| `migrations/` at the repo root | `database/migrations/` | Tables, queries and migrations sit together |
| Go live with `docker compose restart worker` | Claude Code edits the server's `.env` on the owner's instruction, then `docker compose up -d app` | `restart` reuses the old container and its old environment |
| Service named `worker` | Service named `app` | One process serves port 3000 and runs the trading loop |
| Python version unspecified | Python 3.13 everywhere | The laptop has 3.13.7; the container matches |
| Kill command `python -m arbipilot.kill` | `/kill` in Telegram or `POST /trading/kill` | There is no `arbipilot` package in this structure |
| Healthchecks "ping sidecar or in-worker" | In-app ping, production only | Fewer containers; development must not keep the check alive |
| Three build days | Four | Login, the API, the managed database and two environments were added |
| Repo `arbipilot`, folder `~/arbipilot` | Repo and folder `arbipilot_backend`, on the laptop and on the server | The owner created a new backend repo on 2026-11-12 |
| One project containing the dashboard | Backend repo now; a separate frontend repo later | The frontend talks to the backend only through the API |
| `pyproject`/`requirements` written in session 1 | One `requirements.txt`, created by the owner; no `requirements-dev.txt` | The owner's decision on 2026-11-12 |

---

## 17. Open questions — ask the owner during planning

1. **Starting live capital.** The recap says $50, but 8% of $50 is $4, below Binance's usual minimum order value of about $5. Recommended: start at $75 (8% = $6) and keep the 8% cap unchanged. This is the owner's money and his decision.
2. **Day 1 scope.** Day 1 in section 14 is large. Recommended: if it runs long, move the Postman collection start and `decisions.yaml` to Day 2 rather than rushing the database and guard rails.
3. **Meaning of "Server connected successfully".** Assumed to mean the Binance connection. Confirm.
4. **Reaching the production API.** Recommended: keep it private behind the SSH tunnel through shadow week, and add HTTPS (Caddy on the sslip host) with two-factor login in the pre-live bundle. Until then ports 80 and 443 can be closed.
5. **Database public mode.** The laptop and pgAdmin need the public endpoint. AWS advises against leaving public mode on long term. Recommended: public mode with TLS and long generated passwords during the build and shadow week; switch to private mode with pgAdmin and the laptop connecting through an SSH tunnel as part of the pre-live bundle. Check whether Lightsail can restrict the public endpoint to the owner's address, and use that if it can.
6. **Daily AI budget.** How many Claude API calls and how much cost per day, in each environment? Estimate setups per day and cost per call for the chosen model, show the owner the arithmetic against the $100 monthly credit, and let him choose.
7. **Worst-day promotion rule.** Promotion requires `worst_day_drawdown >= -0.02`, but trading already pauses at a 2% daily loss, so the rule almost always passes and tests little. Ask whether to tighten it.
8. **Total exposure.** One position is capped at 8% of equity. Check whether decisions 1–27 limit how many positions can be open at once; if not, ask the owner for a cap before writing the risk engine.
9. **AWS access for Claude Code.** Recommended: the owner creates a limited IAM user (`arbipilot-cli`, Lightsail permissions only) and runs `aws configure` once, with your step-by-step guidance; after that you manage Lightsail yourself. Alternative: he creates the database by clicking in the Lightsail console while you guide him, and you never hold AWS credentials.
10. **Development Telegram bot.** Two running copies of the app cannot both listen with one bot token; Telegram rejects the second. Recommended: a separate development bot (owner action 3). Until it exists, development only sends messages and does not listen for commands.
11. **Password reset channel.** Recommended: a one-time code sent to the owner's Telegram, since there is no email provider. Confirm, or name an email service.
12. **The owner's `.env`.** He created one on 2026-11-10 in the old project folder, which he has since replaced. Check whether a `.env` exists in this folder. If it does, migrate it to the table in section 7, clear any mainnet keys from it, and tell him what you changed (key names only). If it does not, create it.
13. **Git link.** Run `git status` and `git remote -v`. If the folder is not linked to the `arbipilot_backend` repo on GitHub, show the owner an OWNER ACTION NEEDED block or fix it with his approval.
14. **Server folder.** The server has no project folder yet. Recommended: `~/arbipilot_backend`, matching the repo.
