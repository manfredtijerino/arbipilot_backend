# ArbiPilot API

The endpoint table. It is the contract with the future frontend, so it is kept in step with the code: a row says **Built** only when the endpoint exists, has its tests and has its Postman request.

- Every path starts with `/api/v1`. Development: `http://localhost:3000/api/v1`. Production (through the SSH tunnel): `http://localhost:3001/api/v1`.
- Every endpoint needs login (`Authorization: Bearer <access token>`) except the two health endpoints and the five `/auth` endpoints that exist to get a token: register, login, refresh, forgot password and reset password.
- Errors always look like this: `{"error": {"code": "not_found", "message": "This address does not exist."}}`.
- Money is a string, never a number. Times are ISO 8601 in UTC.

## Health (no login)

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/health` | No | No | Is the app alive? Returns environment, trading mode and version. | **Built** |
| GET | `/health/ready` | No | No | Is everything connected? Returns ok or failed for the database, Binance, Claude and Telegram. | **Built** |

### `GET /health`

Always `200` while the app runs.

```json
{"status": "ok", "environment": "development", "trading_mode": "shadow", "version": "0.1.0"}
```

| Field | Meaning |
|---|---|
| `status` | Always `"ok"`. |
| `environment` | `"development"` or `"production"`. |
| `trading_mode` | `"shadow"`, `"testnet"` or `"live"`. |
| `version` | The app's version. |

### `GET /health/ready`

`200` when all four connections work, `503` when any one fails. The body has the same shape in both cases. The answer is reused for 15 seconds, so calling it repeatedly does not call Binance, Anthropic or Telegram each time.

```json
{
  "status": "failed",
  "environment": "development",
  "checks": {
    "database": {"status": "failed", "detail": "could not reach the managed database (host unreachable)"},
    "binance": {"status": "ok", "detail": ""},
    "claude": {"status": "ok", "detail": ""},
    "telegram": {"status": "ok", "detail": ""}
  }
}
```

| Field | Meaning |
|---|---|
| `status` | `"ok"` only when every check is `"ok"`. |
| `environment` | `"development"` or `"production"`. |
| `checks.<name>.status` | `"ok"` or `"failed"`, for `database`, `binance`, `claude`, `telegram`. |
| `checks.<name>.detail` | Empty when ok. When failed, a plain sentence saying why. Never a secret. |

What each check does: `database` runs `SELECT 1` over TLS; `binance` reads Binance's clock and compares it with ours (limit 1000 ms); `claude` looks the configured model up (costs no tokens); `telegram` asks Telegram whether the bot token is accepted (sends no message).

## Login and users

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| POST | `/auth/register` | No (closed once the owner exists) | No | Creates the owner account (email and password). | **Built** |
| POST | `/auth/login` | No | No | Checks email and password; returns an access token and a refresh token. | **Built** |
| POST | `/auth/refresh` | Refresh token | No | Swaps a refresh token for a new pair of tokens. | **Built** |
| POST | `/auth/logout` | Yes | No | Cancels the refresh token. | **Built** |
| POST | `/auth/password/forgot` | No | No | Sends a one-time reset code to the owner's Telegram. | **Built** |
| POST | `/auth/password/reset` | Reset code | No | Sets a new password using the reset code. | **Built** |
| POST | `/auth/password/change` | Yes | No | Changes the password while logged in. | **Built** |
| GET | `/users/me` | Yes | No | Returns the logged-in user's profile. | **Built** |
| PATCH | `/users/me` | Yes | No | Updates the display name. | **Built** |

### How login works

1. `POST /auth/login` returns two tokens.
2. Send the **access token** with every other request: `Authorization: Bearer <access token>`. It works for 30 minutes.
3. When it expires, send the **refresh token** to `POST /auth/refresh` to get a new pair. A refresh token works for 7 days and only once.
4. Without a valid access token, every endpoint outside the "Login: No" rows answers `401 not_authenticated`.

Request bodies refuse unknown fields (`422`). A `422` names the fields that are wrong and never repeats what was sent.

| Error code | Status | When |
|---|---|---|
| `not_authenticated` | 401 | The access token is missing, wrong, expired, or older than the last password change. |
| `invalid_credentials` | 401 | Wrong email or password. An unknown email gets the same answer and the same waits. |
| `too_many_attempts` | 429 | Waiting after wrong passwords: 1 s, 2 s, 4 s ... up to 15 minutes. The `Retry-After` header gives the seconds left. A correct login or a password reset clears it. |
| `invalid_refresh_token` | 401 | The refresh token is unknown, used, cancelled or expired. |
| `registration_closed` | 409 | The owner account already exists. |
| `invalid_reset_code` | 400 | The reset code is wrong, used or expired, or the email is unknown. |
| `invalid_input` | 422 | A field is missing or has the wrong shape. |

### `POST /auth/register`

Works once. `201` with the profile; `409 registration_closed` afterwards.

```json
{"email": "you@example.com", "password": "at least 12 characters", "display_name": "Manfred"}
```

| Field | Rule |
|---|---|
| `email` | Required. Stored in lowercase. |
| `password` | Required. 12 to 128 characters, no other rule. |
| `display_name` | Optional. Up to 100 characters. |

The answer is the profile (see `GET /users/me`). It never contains the password.

### `POST /auth/login`

Body: `{"email": "...", "password": "..."}`. `200`:

```json
{"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 1800}
```

| Field | Meaning |
|---|---|
| `access_token` | Send it as `Authorization: Bearer ...`. |
| `refresh_token` | Keep it; use it only with `/auth/refresh` and `/auth/logout`. |
| `token_type` | Always `"bearer"`. |
| `expires_in` | Seconds until the access token stops working (1800). |

### `POST /auth/refresh`

Body: `{"refresh_token": "..."}`. `200` with the same shape as login. The old refresh token is used up. Using an old one again cancels every token of the account, because it may have been stolen; log in again.

### `POST /auth/logout`

Login needed. Body: `{"refresh_token": "..."}`. `204` with no body. The access token keeps working until its 30 minutes are over.

### `POST /auth/password/change`

Login needed. Body: `{"current_password": "...", "new_password": "..."}`. `200` with a new pair of tokens (same shape as login). Every earlier token stops working. A login wait does not apply here.

### `POST /auth/password/forgot`

Body: `{"email": "..."}`. Always `200`:

```json
{"message": "If the account exists, a code was sent to the owner's Telegram."}
```

The code has six digits, works for 10 minutes and once. Asking again replaces the earlier code. Limits: one code a minute, three an hour, ten a day, counting used and cancelled codes too. When a limit is hit the answer is the same sentence and no code is sent.

### `POST /auth/password/reset`

Body: `{"email": "...", "code": "493 201", "new_password": "..."}` (the space in the code is optional). `200` with a `message`; `400 invalid_reset_code` otherwise. Five wrong codes cancel the code. A successful reset logs out every session and clears any login wait.

### `GET /users/me`

```json
{"id": "3f2b8c1e-0000-4000-8000-000000000001", "email": "you@example.com", "display_name": "Manfred", "created_at": "2026-11-24T15:00:00Z", "last_login_at": "2026-11-24T15:05:00Z"}
```

| Field | Meaning |
|---|---|
| `id` | The account's identifier. |
| `email` | The login email, in lowercase. |
| `display_name` | The name to show, or `null`. |
| `created_at` | When the account was created (UTC). |
| `last_login_at` | The last successful login (UTC), or `null`. |

### `PATCH /users/me`

Body: `{"display_name": "Manfred"}`. The field is required; `null` or `""` clears the name. `200` with the updated profile. The email cannot be changed.

## Connection checks

One request per outside service. Each answers `200` when the service works and `503` when it does not, with the same body either way.

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/integrations/binance` | Yes | No | Tests the Binance connection: reachable, clock difference, keys valid, trading allowed, withdrawals disabled, fee rates. | **Built** |
| GET | `/integrations/binance/balances` | Yes | No | Returns the Spot balances for USDT and BNB. | **Built** |
| GET | `/integrations/database` | Yes | No | Tests the database: name, version, latest migration applied. | **Built** |
| GET | `/integrations/claude` | Yes | No | Tests the Claude API key and model. Today's usage against the budget arrives with the AI budget (stage 9). | **Built** |
| POST | `/integrations/telegram/test` | Yes | No | Sends a test message to the owner's Telegram. | **Built** |
| POST | `/integrations/healthchecks/test` | Yes | No | Sends a test ping to Healthchecks.io. | **Built** |
| GET | `/integrations/server` | Yes | No | Reports on the machine the app runs on: public address, uptime, memory, disk, clock sync. | **Built** |

### What every connection check answers

| Field | Meaning |
|---|---|
| `status` | `"ok"`: it works. `"failed"`: it does not (HTTP `503`). `"not_configured"`: the setting is empty on this machine on purpose (HTTP `200`). |
| `detail` | When failed: what is wrong, in plain words. Otherwise empty or a note. Never contains a key, a token or an address that is a secret. |

A field that is `null` means "could not be checked here" or "Binance did not say". A missing answer is never read as safe: it fails the check. None of these requests places an order or moves money; the Binance ones only read.

They cannot be run in a loop, because each one calls an outside service and Binance counts every call against the address the trading loop also uses:
- A `GET` check's answer is reused for 15 seconds. Asking again within that time returns the same answer without calling the service.
- The two `POST` checks send something real, so each works at most once a minute. Sooner than that: `429` `too_many_requests` with a `Retry-After` header.

If the database is down, every endpoint that needs login answers `503` `database_unavailable`, because checking the token needs the database.

### `GET /integrations/binance`

```json
{
  "status": "ok",
  "detail": "",
  "host": "api.binance.com",
  "reachable": true,
  "clock_difference_ms": 60,
  "keys": [
    {
      "name": "testnet",
      "exchange": "testnet",
      "ok": true,
      "valid": true,
      "trading_allowed": true,
      "withdrawals_enabled": null,
      "ip_restricted": null,
      "spot_only": null,
      "maker_fee": "0.00100000",
      "taker_fee": "0.00100000",
      "detail": "the testnet has no withdrawals and no IP lock, so those two cannot be checked here"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `host` | The Binance address used for market data in the current trading mode. |
| `reachable` | Binance answered and the clocks agree within 1000 ms. When `false`, no key is sent. |
| `clock_difference_ms` | Binance's clock minus this machine's. |
| `keys` | One entry per key present in `.env`: `testnet`, `read`, `trade`. The laptop holds only `testnet`. |
| `keys[].valid` | Binance accepted the key and its signature. |
| `keys[].trading_allowed` | The key may place Spot orders. Expected: `true` for `testnet` and `trade`, `false` for `read`. |
| `keys[].withdrawals_enabled` | Must be `false`. `true` fails the check. Mainnet keys only; `null` on the testnet, which has no such setting. |
| `keys[].ip_restricted` | The key only works from a fixed address. Must be `true` for mainnet keys; `null` on the testnet. |
| `keys[].spot_only` | Margin, futures, options, internal transfers, universal transfers and portfolio margin are all off. Must be `true` for mainnet keys (the bot is Spot only); `null` on the testnet. |
| `keys[].maker_fee`, `taker_fee` | The account's fee per side as Binance reports it, before the BNB discount. Text. The testnet reports zero. |
| `keys[].ok` | Everything above is as it should be for this key. |

### `GET /integrations/binance/balances`

```json
{
  "status": "ok",
  "detail": "pretend money on the Binance testnet",
  "exchange": "testnet",
  "balances": [
    {"asset": "USDT", "free": "10000.00000000", "locked": "0.00000000", "total": "10000.00000000"},
    {"asset": "BNB", "free": "1.00000000", "locked": "0.00000000", "total": "1.00000000"}
  ]
}
```

`exchange` says where the numbers come from. In testnet mode, and on the laptop (which has no mainnet key), it is `"testnet"`. On the server in shadow or live mode it is `"mainnet"`, read with the read key. `free` can be used now, `locked` is held by open orders. Always both assets, `"0"` when Binance lists none.

### `GET /integrations/database`

```json
{"status": "ok", "detail": "", "name": "arbipilot_dev", "version": "18.6", "applied_migration": "0002", "latest_migration": "0002"}
```

`applied_migration` is what the tables are at; `latest_migration` is what the code expects. When they differ the check fails.

### `GET /integrations/claude`

```json
{"status": "ok", "detail": "usage against the daily budget is not tracked yet", "model": "claude-sonnet-5-5", "usage_today_usd": null, "daily_budget_usd": null}
```

Looks the model up by name, which proves the key works and costs no tokens. The two usage fields are `null` until stage 9.

### `GET /integrations/server`

```json
{
  "status": "ok",
  "detail": "",
  "environment": "development",
  "app_uptime_seconds": 300,
  "machine_uptime_seconds": 86400,
  "memory_total_mb": 16384,
  "memory_available_mb": 8192,
  "disk_total_gb": 460.0,
  "disk_free_gb": 120.5,
  "public_ip": "203.0.113.7",
  "expected_public_ip": null,
  "public_ip_matches": null,
  "clock_difference_ms": 60
}
```

The uptime, memory and disk fields are `null` (and the check fails) only if the machine refuses to report them. `public_ip` is the address the internet sees this machine as. On the server `expected_public_ip` is the address the Binance keys are locked to (`EXPECTED_PUBLIC_IP`), and the check fails when the two differ. On the laptop nothing is expected, so `public_ip_matches` is `null`.

### `POST /integrations/telegram/test`

No body. Sends one real message. `{"status": "ok", "detail": "message sent; look at Telegram"}`.

### `POST /integrations/healthchecks/test`

No body. Sends one real ping. On the laptop: `{"status": "not_configured", "detail": "HEALTHCHECKS_PING_URL is empty; it is filled in on the server only"}`.

## Market data

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/market/symbols` | Yes | No | Lists the pairs the bot watches, with each pair's minimum order value, price step and quantity step. | **Built** |
| GET | `/market/ticker/{symbol}` | Yes | No | Returns the latest price for one pair. | **Built** |
| GET | `/market/stream/status` | Yes | No | Shows whether the live price stream is connected and how old the last message is. | **Built** |

The app keeps one live connection to Binance for all watched pairs (`MARKET_SYMBOLS` in `.env`) and remembers the latest price of each. These three requests only read that memory: none of them calls Binance. Prices, quantities and order values are text (`"59896.01000000"`), never JSON numbers. Times are UTC.

### `GET /market/symbols`

```json
{
  "loaded_at": "2026-11-27T18:06:46.512345Z",
  "stale": false,
  "symbols": [
    {
      "symbol": "BTCUSDT",
      "base_asset": "BTC",
      "quote_asset": "USDT",
      "status": "TRADING",
      "trading": true,
      "min_order_value": "5.00000000",
      "tick_size": "0.01000000",
      "step_size": "0.00001000",
      "min_quantity": "0.00001000"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `loaded_at` | When the rules were last read from Binance (at startup, then every 6 hours). |
| `stale` | `true` when the rules could not be refreshed for over 12 hours. Old rules are kept, but should not be trusted for new orders. |
| `trading` | `true` only when Binance says the pair is open and Spot trading is allowed. |
| `min_order_value` | The smallest order Binance accepts, in the quote asset (USDT). |
| `tick_size` | Prices must be a multiple of this. |
| `step_size` | Quantities must be a multiple of this. |
| `min_quantity` | The smallest quantity Binance accepts. |

`503` `market_not_ready` until the rules have been read (a second or two after startup); the message says why.

### `GET /market/ticker/{symbol}`

`{symbol}` is a watched pair, in any letter case: `/market/ticker/BTCUSDT`.

```json
{
  "symbol": "BTCUSDT",
  "bid": "59896.00000000",
  "bid_quantity": "1.20514000",
  "ask": "59896.01000000",
  "ask_quantity": "3.80211000",
  "last_price": "59896.01000000",
  "last_quantity": "0.00042000",
  "last_trade_at": "2026-11-27T18:06:52.101000Z",
  "updated_at": "2026-11-27T18:06:52.140211Z",
  "age_ms": 4,
  "last_trade_age_ms": 43,
  "stale": false
}
```

| Field | Meaning |
|---|---|
| `bid` / `bid_quantity` | The best price someone will buy at, and how much they want. |
| `ask` / `ask_quantity` | The best price someone will sell at, and how much they offer. |
| `last_price` / `last_quantity` / `last_trade_at` | The last trade. `null` until the first trade arrives. |
| `updated_at` / `age_ms` | When the bid and ask last arrived, and how long ago. A trade does not count: a fresh trade says nothing about the bid and ask. |
| `last_trade_age_ms` | How long ago the last trade arrived. `null` until the first one. |
| `stale` | `true` when the bid and ask are older than 10 seconds, the stream is not connected, or the stream reconnected and has not sent this pair's bid and ask again yet. Do not act on a stale price. A very quiet pair can be stale simply because nothing changed; that is the safe side. |

Errors: `404` `unknown_symbol` (not on the watch list), `422` (not a pair name), `503` `market_not_ready` (no price has arrived yet).

### `GET /market/stream/status`

```json
{
  "status": "connected",
  "detail": "",
  "host": "stream.binance.com",
  "streams": ["btcusdt@bookTicker", "btcusdt@aggTrade"],
  "connected_since": "2026-11-27T18:06:46.201000Z",
  "last_message_at": "2026-11-27T18:36:46.498000Z",
  "last_message_age_ms": 3,
  "messages_received": 612044,
  "messages_ignored": 0,
  "reconnects": 0,
  "recording": {
    "enabled": false,
    "active": false,
    "file": null,
    "lines_written": 0,
    "folder_megabytes": 0.0,
    "detail": "off (MARKET_RECORDING is not true)"
  }
}
```

| Field | Meaning |
|---|---|
| `status` | `connected`; `connecting` (down and retrying, `detail` says why); `not_configured` (`BINANCE_WS_URL` is wrong or empty). Always answers `200`. |
| `streams` | Two per pair: `bookTicker` (best bid and ask) and `aggTrade` (every trade). |
| `reconnects` | How many times the connection had to be opened again since the app started. Binance itself closes every connection after 24 hours, so this grows by at least one a day. |
| `messages_ignored` | Messages the app could not use. Should stay at or near zero. |
| `recording` | Whether the stream is being saved to `recordings/` (`MARKET_RECORDING=true`). A new file starts at each app start and each UTC day. It stops by itself at 2 GB, or when the disk has under 1 GB free. |

## Trading control

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/trading/status` | Yes | No | Environment, mode, running or paused (and why), open positions, today's profit or loss. | Planned |
| GET | `/trading/risk` | Yes | No | The current limits from `decisions.yaml` and how much of each is used today. | **Built** |
| POST | `/trading/kill` | Yes | No | Pauses trading and cancels open orders. | Planned |
| POST | `/trading/resume` | Yes | No | Resumes trading after a pause. | Planned |
| POST | `/trading/orders/test` | Yes | **Yes** | Sends one test order through the full path (risk engine, router, fill) in shadow or testnet. | Planned |

### `GET /trading/risk`

The owner's limits, and how much of each is used right now. Money and shares are text. No request can change a limit: they change only in `decisions.yaml`.

```json
{
  "limits": {
    "max_position_pct_equity": "0.08",
    "daily_loss_pause_pct": "0.02",
    "max_open_positions": 3,
    "max_positions_per_symbol": 1,
    "max_orders_per_minute": 8
  },
  "usage": {
    "equity": "300",
    "equity_source": "paper starting balance (no trades yet)",
    "max_position_value": "24.00",
    "day": "2026-11-27",
    "day_start_equity": "300",
    "day_profit_or_loss": "0",
    "daily_loss_limit_value": "6.00",
    "entries_paused": false,
    "pause_reason": "",
    "open_positions": 0,
    "orders_last_minute": 0
  }
}
```

| Field | Meaning |
|---|---|
| `limits.max_position_pct_equity` | One trade may use at most this share of the account. `"0.08"` = 8%. |
| `limits.daily_loss_pause_pct` | After losing this share in one UTC day, no new trade is opened until the next UTC day. `"0.02"` = 2%. |
| `limits.max_open_positions` | How many trades may be open at once, over all pairs. |
| `limits.max_positions_per_symbol` | How many trades may be open at once in one pair. |
| `limits.max_orders_per_minute` | At most this many orders in any 60 seconds (a guard against a runaway bug). |
| `usage.equity` | What the account is worth now: cash plus coins held. |
| `usage.equity_source` | Where that value comes from. Until stage 7 it is the paper starting balance. |
| `usage.max_position_value` | The biggest trade allowed right now: the share above times `equity`. |
| `usage.day` / `usage.day_start_equity` | The UTC day being counted, and the account's value when it began. |
| `usage.day_profit_or_loss` | Today's result. Negative is a loss. |
| `usage.daily_loss_limit_value` | The loss at which new trades stop today. |
| `usage.entries_paused` / `usage.pause_reason` | `true` once today's loss reached the limit, and why. Closing trades is still allowed. |
| `usage.open_positions` | Trades open now, including entry orders still waiting. |
| `usage.orders_last_minute` | Orders approved in the last 60 seconds. |

What the risk engine does with an order (used from stage 7 on): **approved**, **reduced** (cut to the position cap or to the free cash), or **rejected** with one of these codes: `trading_paused`, `unknown_symbol`, `rules_stale`, `pair_not_trading`, `price_unavailable`, `price_stale`, `no_equity`, `daily_loss_pause`, `position_exists`, `max_open_positions`, `order_rate_limit`, `below_minimum`, `invalid_order`, `nothing_to_sell`.

## Data

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/trades` | Yes | No | Lists trades, newest first, with filters for pair, date and mode. | Planned |
| GET | `/trades/{id}` | Yes | No | One trade in full: entry, exit, fees, AI verdict, risk decision. | Planned |
| GET | `/orders` | Yes | No | Lists orders and their status. | Planned |
| GET | `/positions` | Yes | No | Lists open positions. | Planned |
| GET | `/signals` | Yes | No | Lists setups the strategy found and what was decided about each. | Planned |
| GET | `/performance/summary` | Yes | No | Expectancy per trade, win rate, drawdown, and the comparison with the two baselines. | Planned |
| GET | `/performance/daily` | Yes | No | Profit or loss per day. | Planned |
| GET | `/reconciliation/latest` | Yes | No | The latest comparison between our records and the exchange. | Planned |

## AI

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/ai/usage` | Yes | No | Calls, tokens and cost today and this month, against the budget. | Planned |
| GET | `/ai/decisions` | Yes | No | Recent AI verdicts with their reasons. | Planned |
| POST | `/ai/evaluate` | Yes | **Yes** | Sends a sample setup to the AI and returns its verdict. Costs tokens. | Planned |

## System

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/system/config` | Yes | No | The non-secret configuration in use: environment, mode, limits, model. Never a secret. | Planned |
| GET | `/system/logs` | Yes | No | Recent log lines, filtered by level. | Planned |
| GET | `/system/events` | Yes | No | Recent alerts and important events. | Planned |

## Deliberately missing

- No endpoint switches to live trading or changes a risk limit.
- No endpoint places an order in production.
- No endpoint returns a secret.
