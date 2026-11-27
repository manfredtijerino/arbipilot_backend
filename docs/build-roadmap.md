# ArbiPilot backend: build roadmap

The step-by-step path from an empty repo to a backend that runs in production with paper money, fully tested, ready for the frontend. Agreed with the owner on 2026-11-23.

This file says **what is built in which order, why, and how each step is proven**. The detail of each topic stays in `docs/project-brief.md`; the endpoint table stays in `docs/api.md`.

## 1. The rule of the gate

Every stage below ends at a gate. **The next stage does not start until the gate is passed.**

A gate is passed when all of these are true:

| # | Check | Who | Why |
|---|---|---|---|
| 1 | Automated checks are green: `/preflight` (format, lint, unit tests) and the integration tests on `arbipilot_test` | Claude Code | Because a later stage built on a broken one hides the cause of every new failure |
| 2 | The reviewers found no blocking issue (`security-reviewer`, `trading-reviewer`) | Claude Code | Because login and money code get a second look that is not anchored on the author's view |
| 3 | Every endpoint of the stage has a Postman request, and **the owner ran them against development and they pass** | Owner | Because the owner must see each piece working with his own hands, not take it on trust |
| 4 | Where the stage writes data, the owner has seen it in pgAdmin | Owner | Because the records are what the scoreboard is built from |
| 5 | The owner says "approved", and the date is written in the status table (section 3) | Owner | Because moving on is his decision |

**Example:** the login stage is not finished when the code is written. It is finished when the tests pass, the owner has registered and logged in from Postman, has seen his user row in pgAdmin, and has said "approved".

If a stage runs long, the stage is split; tests are never cut to keep a schedule.

## 2. The main objectives, and where each is proven

From `docs/project-brief.md` §2. Each objective has a stage where it is built and a stage where it is proven for real.

| # | Objective | Why | Example | Built in | Proven in |
|---|---|---|---|---|---|
| 1 | Prove positive expectancy per trade with paper money before any real money | Because the target is profit per trade after fees, not dollars per day | Promote only after at least 100 paper trades whose results are reliably above zero | Stages 7, 10 | Stage 13 |
| 2 | Protect capital first | Because the account is small and a few bad trades would end the experiment | A position is capped at 8% of equity; trading pauses after a 2% daily loss | Stage 6 | Stages 8, 13 |
| 3 | Trade live on a small base, then scale to $300 | Because a live bot is the goal and paper trading is the test stage | Start small, grow once it holds up | Stage 15 | Stage 15 |
| 4 | Run 24/7 without supervision | Because the owner is asleep or working for most of the bot's hours | An alert arrives if the app goes quiet for 10 minutes | Stages 5, 12 | Stage 13 |
| 5 | Keep the owner in control from a phone | Because he must be able to stop it at once from anywhere | `/kill` in Telegram pauses trading | Stage 8 | Stages 12, 13 |
| 6 | Stay cheap and simple | Because complexity waits until there is money to protect | One server, one database machine, no extra services during the paper period | Every stage | Every stage |
| 7 | Be honest in measurement | Because an optimistic simulator would promote a losing strategy | A paper buy at 100.00 counts as filled only after a real trade prints below 100.00 | Stage 7 | Stages 10, 13 |

## 3. Status

| Stage | Name | Endpoints | Status |
|---|---|---|---|
| 1 | Foundation and connections | 2 | **Passed 2026-11-23.** Owner started the app, ran both requests in Postman (200), approved. Commit `215c7b8` on `feature/foundation` |
| 2 | Tables and migrations | 0 | **Passed 2026-11-24.** Migrations `0001` and `0002` on `arbipilot_dev` and `arbipilot_test`; owner checked the tables in pgAdmin and approved |
| 3 | Login and users | 9 | **Passed 2026-11-26.** Owner ran all nine endpoints from his own Postman collection, checked the `users` row in pgAdmin and approved. Commit `7a3ab99`, merged to `main` by pull request #1 (`8bf4847`) |
| 4 | Connection checks | 7 | **Passed 2026-11-27.** Owner built the seven requests in his own Postman collection, ran them against development and approved. Branch `feature/connection-checks`. Still to prove at stage 12 with the mainnet keys: withdrawals off, IP lock, Spot only |
| 5 | Market data | 3 | **Passed 2026-11-27.** Owner built the three requests in his own Postman collection, ran them against development and approved. One-hour stream run with a forced drop at minute 30: reconnected in 2 seconds, 712,817 messages, 0 unusable. Branch `feature/market-data`. Watched pairs are a placeholder (`MARKET_SYMBOLS`) until `OBJECTIVES.md` names them |
| 6 | Risk limits and the risk engine | 1 | Blocked: needs owner action 0 |
| 7 | Strategy and honest paper fills | 1 | Blocked: needs owner action 0 |
| 8 | Order path and the kill switch | 5 | Not started |
| 9 | AI judge and its budget | 3 | Not started |
| 10 | Records and the scoreboard | 7 | Not started |
| 11 | Testnet run | 2 | Not started |
| 12 | Production, tested end to end | all 40 | Not started |
| 13 | Paper-money period in production | — | Not started |
| 14 | Frontend (separate repo) | — | Starts after stage 12 |
| 15 | Real money | — | Only on the owner's word |

Claude Code updates this table when a gate is passed, with the date.

## 4. The stages

### Stage 1: Foundation and connections

- **Goal:** `python server.py` starts, checks its connections, and says truthfully what works.
- **Why:** Because every later stage needs a database, Binance, the AI and Telegram, and a failure must be visible in the first second, not hours later.
- **Example:** with a wrong database password the app prints `✖ Database connection failed: the password was refused` and stops, instead of starting and failing on the first trade.
- **Built:** settings and guard rails (`config/`), the startup lines, the database on Lightsail with `arbipilot_dev`, `arbipilot_test`, `arbipilot_prod`, the error shape, log lines with secrets hidden.
- **Endpoints:** `GET /health`, `GET /health/ready`.
- **Gate:** the owner starts the app himself and sees four ✔ lines, `Environment: DEVELOPMENT`, `Mode: SHADOW`; both requests pass in Postman.
- **Open before the gate:** owner action 2b (empty the production-only keys on the laptop), import the Postman collection, first commit of this work.

### Stage 2: Tables and migrations

- **Goal:** tables are created and changed only by versioned scripts (migrations), the same way in all three databases.
- **Why:** Because a table changed by hand in one database and not another is the classic cause of "works on my laptop, breaks in production".
- **Example:** adding a `last_login_at` column is one migration file. It runs on `arbipilot_dev` today and on `arbipilot_prod` at the next deploy, giving identical tables.
- **Built:** Alembic setup, the first tables (users, refresh tokens, reset codes), the integration-test setup that refuses any database whose name does not end in `_test`. The database itself enforces: one owner row only, emails in lowercase, one unused reset code per user. Migrations refuse an unknown option, check the name of the database they reached, and refuse a downgrade in production.
- **Gate:** `alembic upgrade head` succeeds on `arbipilot_dev`; the owner sees the tables in pgAdmin; integration tests pass on `arbipilot_test`. Also proves from the app's side that the development user is refused by `arbipilot_prod`. (The read-only user can only enter `arbipilot_prod`, so its rights are proven at stage 12, when production has tables.)

### Stage 3: Login and users

- **Goal:** only the owner can use the API.
- **Why:** Because later endpoints pause trading and show balances, so nothing except health may answer a stranger.
- **Example:** `GET /users/me` without a token answers 401; after `POST /auth/login` the same request answers with the owner's profile.
- **Built (tests written first):** one owner account, passwords hashed with Argon2, a 30-minute access token and a 7-day refresh token, a reset code sent by Telegram (10 minutes, usable once), a lock after five wrong passwords.
- **Endpoints:** `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/password/forgot`, `/auth/password/reset`, `/auth/password/change`, `GET /users/me`, `PATCH /users/me`.
- **Gate:** the owner registers, logs in, receives a reset code in Telegram and sets a new password, all from Postman; a second registration is refused; a request without a token is refused.
- **Carried over from the stage 2 security review (must be handled here):**
  - Never log or return the database's own error text: a "duplicate" error contains the email or token hash.
  - Hash the reset code with Argon2 or a keyed hash; a plain hash of six digits can be reversed in under a second.
  - Count wrong passwords and wrong codes inside one SQL statement (`SET x = x + 1`), so parallel guesses cannot beat the limit.
  - Cancel the old reset code before issuing a new one, and limit how often a code can be requested.
  - A token issued in the same second as a password change must still work: compare times at whole-second precision.
  - A lock after five wrong passwords lets a stranger who knows the email keep the owner out. Prefer growing delays, and keep the Telegram reset working during a lock.

### Stage 4: Connection checks

- **Goal:** one request per outside service that says ok, or exactly what is wrong.
- **Why:** Because when something fails at 3 a.m. the first question is "which connection?", and the answer must take one click.
- **Example:** `GET /integrations/binance` reports reachable, clock difference 60 ms, key valid, trading allowed, withdrawals disabled.
- **Endpoints:** `GET /integrations/binance`, `/integrations/binance/balances`, `/integrations/database`, `/integrations/claude`, `/integrations/server`, `POST /integrations/telegram/test`, `/integrations/healthchecks/test`.
- **Gate:** the owner runs all seven in Postman; the Telegram test message arrives; the Binance check confirms withdrawals are disabled on the key.
- **Note (2026-11-26):** Binance's testnet has no withdrawals and no key settings, so on the laptop those fields are `null`. The check for the real keys (withdrawals off, locked to an IP address, Spot only) is built and tested with pretend answers, and is proven for real at stage 12 on the server.

### Stage 5: Market data

- **Goal:** the app knows the pairs, their trading rules and their live prices, and records the price stream.
- **Why:** Because every decision starts from prices, and recorded streams become test data, so trading tests never need the network.
- **Example:** `GET /market/ticker/BTCUSDT` returns the latest price; one recorded night of prices replays in a test in seconds.
- **Built:** the Binance client, each pair's minimum order value and step sizes read at startup, the live stream with automatic reconnect, the recorder.
- **Endpoints:** `GET /market/symbols`, `/market/ticker/{symbol}`, `/market/stream/status`.
- **Carry-over from the stage 4 reviews (Binance client):**
  - One long-lived shared HTTP client instead of a new one per call; it must never follow redirects (a redirect would carry the key header to another host).
  - Read Binance's `Retry-After` and used-weight headers and slow down before a limit is hit; a ban on the server's address also stops trading.
  - Parse prices and amounts as `Decimal` from the start (`parse_float=Decimal`), never through a float.
- **Gate:** the three requests pass in Postman; the stream stays connected for one hour and reconnects by itself after a forced drop; a recorded file exists and replays in a test.

### Stage 6: Risk limits and the risk engine

- **Goal:** one gatekeeper that every order must pass, with limits written in one file.
- **Why:** Because protecting capital comes first, and no signal, not even the AI's, may go around the limits.
- **Example:** a $40 order on $300 of equity is cut to $24 (the 8% cap); after a 2% loss in one UTC day every new entry is refused.
- **Built (tests written first):** `decisions.yaml` and its loader, position cap, daily-loss pause, order-rate limit, minimum-order check. Money is `Decimal` throughout.
- **Endpoint:** `GET /trading/risk`.
- **Needs first:** owner action 0, because the limit values come from `docs/day0-recap.md` and the decisions file and must not be guessed.
- **Gate:** the owner reads the limits in Postman and confirms they are his; the tests show each limit refusing or shrinking an order.
- **Carried over from the stage 5 reviews (must be handled here or at stage 8):**
  - The risk engine refuses an entry when `ticker().stale` is true, when the pair's rules are `stale`, or when the pair's `trading` is false.
  - The owner decides whether "a price older than 10 seconds is stale" (`QUOTE_STALE_SECONDS` in `exchange/config.py`) stays a technical value or moves into `decisions.yaml`.
  - Stream down for longer than a set time pauses new entries and sends a Telegram alert (today it is only a log line).
  - Measure the delay between Binance's trade time and our clock, and treat a large delay as stale.
  - At `/deploy`: decide where `recordings/` lives on the server (a volume, not inside the container) before `MARKET_RECORDING=true` is used there.

### Stage 7: Strategy and honest paper fills

- **Goal:** the app finds setups and simulates orders the way the real exchange would treat them.
- **Why:** Because the paper results decide whether real money is ever used, so the simulator must not flatter the strategy.
- **Example:** a paper buy at 100.00 fills only after a real trade prints below 100.00, 150 ms after the order was placed. Touching 100.00 is not enough.
- **Built (tests written first):** the strategy from `OBJECTIVES.md`, the paper-fill simulator, fee maths at 0.075% per side.
- **Endpoint:** `GET /signals`.
- **Needs first:** owner action 0 (`OBJECTIVES.md` defines the strategy).
- **Gate:** replaying a recorded stream produces the same signals and fills every time; the owner sees signals listed in Postman and the fee on a sample trade matches a hand calculation (a $24 trade pays $0.018 per side).

### Stage 8: Order path and the kill switch

- **Goal:** one path for every order (signal → risk engine → router → fill → record) and a stop button that works from the phone.
- **Why:** Because the same path must be used in paper, testnet and live mode, so that what was tested is what trades; and the owner must be able to stop it at once.
- **Example:** `POST /trading/kill` pauses trading and cancels open orders; after a restart the app is still paused until `POST /trading/resume`.
- **Endpoints:** `GET /trading/status`, `POST /trading/kill`, `/trading/resume`, `/trading/orders/test` (development only), `GET /orders`.
- **Carry-over from the stage 4 reviews (must be done before any order is signed):**
  - Sign with the local clock corrected by a recently measured offset per host, or refuse a clock more than 500 ms ahead. Today's 1000 ms tolerance leaves no margin on the "ahead" side, where Binance refuses at 1000 ms.
  - An error type for orders that carries Binance's code, the HTTP status and `Retry-After` as fields. The read-only one carries a sentence only.
  - A timeout on an order means "outcome unknown": look the order up by its client order ID, never send it again. The read-only handler must not be reused for orders.
  - One function that picks the order key: none in shadow, the testnet key in testnet, the trade key only in live. The router never picks from the list of configured keys itself.
  - Compare the fee Binance charged on each fill with the configured fee.
- **Gate:** the owner sends a test order from Postman in paper mode and follows it into pgAdmin; an oversized test order comes out shrunk; kill, restart, still paused, resume. `/kill` from Telegram is proven here if the development bot exists, otherwise at stage 12.

### Stage 9: AI judge and its budget

- **Goal:** Claude evaluates each setup and answers in a fixed format, inside a daily budget.
- **Why:** Because the AI adds judgement on top of fixed rules, but it is a judge and never a safety system: when it fails, the bot takes no new entries and keeps managing open positions by rules.
- **Example:** the AI answers `{"decision": "skip", "reason": "..."}`; at 100% of the day's budget it is not called again until the next UTC day.
- **Endpoints:** `GET /ai/usage`, `/ai/decisions`, `POST /ai/evaluate` (development only, costs tokens).
- **Gate:** the owner sends a sample setup from Postman and reads the verdict; with a deliberately wrong key the app keeps running with new entries off and one Telegram alert; the budget stop is shown by a test.

### Stage 10: Records and the scoreboard

- **Goal:** every trade is stored in full and scored honestly against doing nothing.
- **Why:** Because the decision to use real money rests on these numbers.
- **Example:** `GET /performance/summary` shows profit per trade after fees, win rate and drawdown, next to "just held USDT" and "just held BTC".
- **Endpoints:** `GET /trades`, `/trades/{id}`, `/positions`, `/performance/summary`, `/performance/daily`, `/system/config`, `/system/events`.
- **Gate:** the owner picks one trade in Postman and checks its entry, exit, fees, AI verdict and risk decision against pgAdmin; the summary matches a hand calculation on a small set of trades.

### Stage 11: Testnet run

- **Goal:** prove the plumbing with real orders on Binance's fake exchange.
- **Why:** Because paper mode never talks to Binance's order system. Signing, order types and fill messages are only proven by sending real requests. Testnet fees are zero, so this proves plumbing, never profit.
- **Example:** a `LIMIT_MAKER` order is accepted by the testnet, its fill arrives, and our records match the testnet balances within $0.05.
- **Endpoints:** `GET /reconciliation/latest`, `/system/logs`. The stage 4 connection checks are run again in testnet mode.
- **Gate:** a full round trip (buy, sell) on testnet recorded correctly; reconciliation shows no difference; a retried order does not create a duplicate.

### Stage 12: Production, tested end to end

- **Goal:** the backend runs on the server with paper money, and every endpoint is tested there.
- **Why:** Because production differs from the laptop (Docker, another `.env`, real Binance keys, the production database), and a difference is found by testing, not by assuming.
- **Example:** the same Postman collection, switched to the Production environment, runs through the SSH tunnel and every request passes.
- **Built:** the Docker setup, the first `/deploy`, migrations on `arbipilot_prod`, the production `.env`, the Healthchecks ping, `/deploy-check`.
- **Gate:** all 40 endpoints pass from Postman against production (the two development-only ones must answer 404 there); the startup lines show `Environment: PRODUCTION`, `Mode: SHADOW`; `/kill` works from the phone; stopping the app on purpose produces an alert within 10 minutes; the read-only pgAdmin connection can read and cannot change.
- **Before this stage's deploy (from the stage 3 security review):**
  - `POST /auth/register` is open to whoever calls it first. On the server, create the owner account with a command (`scripts/create_owner.py`) or require a one-time setup value, so nobody else can become the owner.
  - A stranger who knows the owner's email can still slow the owner down: keep login at the 15-minute wait, use up the three reset codes an hour. A limit per caller address in front of `/auth` fixes this and must exist before the API is reachable from the internet (pre-live bundle, with HTTPS).
- **This gate is the end of the backend build.** After it, the frontend may start.

### Stage 13: Paper-money period in production

- **Goal:** let the bot trade with paper money on live market data, around the clock, and study the result.
- **Why:** Because this is the only evidence for or against using real money: the strategy, the AI's judgement and the risk limits working together on real prices.
- **Example:** after 100 paper trades the scoreboard shows whether profit per trade after fees is reliably above zero, and whether the AI's "skip" decisions avoided losers or winners.
- **What is studied:** profit per trade after fees, drawdown, the two baselines, how often the AI agreed and whether it helped, how often the risk engine shrank or refused orders, uptime and reconnects, AI cost per day.
- **Gate:** the promotion criteria in `decisions.yaml` are met (at least 100 paper trades and the other values from `docs/day0-recap.md`). If they are not met, the strategy is changed in development and the period starts again. No real money.

### Stage 14: Frontend (separate repo)

- Starts after stage 12 and can run alongside stage 13. It talks to this backend only through the API described in `docs/api.md`. It is part of the pre-live bundle (dashboard with two-factor login, HTTPS and the other deferred items).

### Stage 15: Real money

- **Only** after stage 13's gate is passed, the pre-live bundle is done, and the owner tells Claude Code in his own words to go live. It starts on a small base and scales toward $300 while the results hold.

## 5. Endpoint count

2 (health) + 9 (login and users) + 7 (connection checks) + 3 (market) + 5 (trading control) + 8 (data) + 3 (AI) + 3 (system) = 40. Stage 12 runs all of them against production.

## 6. What this file does not decide

- Strategy details and limit values: `OBJECTIVES.md`, the decisions file and `docs/day0-recap.md` (owner action 0; not yet in the repo).
- The examples for stages 6 to 13 come from `docs/project-brief.md`. They are corrected here once those three files are in the repo.
