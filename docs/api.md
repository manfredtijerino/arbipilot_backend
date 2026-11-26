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

## Integration checks

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/integrations/binance` | Yes | No | Tests the Binance connection: reachable, clock difference, keys valid, trading allowed, withdrawals disabled, fee rates. | Planned |
| GET | `/integrations/binance/balances` | Yes | No | Returns the Spot balances for USDT and BNB. | Planned |
| GET | `/integrations/database` | Yes | No | Tests the database: name, version, latest migration applied. | Planned |
| GET | `/integrations/claude` | Yes | No | Tests the Claude API key and model; returns today's usage against the budget. | Planned |
| POST | `/integrations/telegram/test` | Yes | No | Sends a test message to the owner's Telegram. | Planned |
| POST | `/integrations/healthchecks/test` | Yes | No | Sends a test ping to Healthchecks.io. | Planned |
| GET | `/integrations/server` | Yes | No | Reports on the machine the app runs on: public address, uptime, memory, disk, clock sync. | Planned |

## Market data

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/market/symbols` | Yes | No | Lists the pairs the bot watches, with each pair's minimum order value. | Planned |
| GET | `/market/ticker/{symbol}` | Yes | No | Returns the latest price for one pair. | Planned |
| GET | `/market/stream/status` | Yes | No | Shows whether the live price stream is connected and how old the last message is. | Planned |

## Trading control

| Method | Path | Login | Dev only | What it does | Status |
|---|---|---|---|---|---|
| GET | `/trading/status` | Yes | No | Environment, mode, running or paused (and why), open positions, today's profit or loss. | Planned |
| GET | `/trading/risk` | Yes | No | The current limits from `decisions.yaml` and how much of each is used today. | Planned |
| POST | `/trading/kill` | Yes | No | Pauses trading and cancels open orders. | Planned |
| POST | `/trading/resume` | Yes | No | Resumes trading after a pause. | Planned |
| POST | `/trading/orders/test` | Yes | **Yes** | Sends one test order through the full path (risk engine, router, fill) in shadow or testnet. | Planned |

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
