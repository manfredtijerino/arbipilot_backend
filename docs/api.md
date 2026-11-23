# ArbiPilot API

The endpoint table. It is the contract with the future frontend, so it is kept in step with the code: a row says **Built** only when the endpoint exists, has its tests and has its Postman request.

- Every path starts with `/api/v1`. Development: `http://localhost:3000/api/v1`. Production (through the SSH tunnel): `http://localhost:3001/api/v1`.
- Every endpoint needs login (`Authorization: Bearer <access token>`) except the two health endpoints.
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
| POST | `/auth/register` | No (closed once the owner exists) | No | Creates the owner account (email and password). | Planned |
| POST | `/auth/login` | No | No | Checks email and password; returns an access token and a refresh token. | Planned |
| POST | `/auth/refresh` | Refresh token | No | Swaps a refresh token for a new access token. | Planned |
| POST | `/auth/logout` | Yes | No | Cancels the refresh token. | Planned |
| POST | `/auth/password/forgot` | No | No | Sends a one-time reset code to the owner's Telegram. | Planned |
| POST | `/auth/password/reset` | Reset code | No | Sets a new password using the reset code. | Planned |
| POST | `/auth/password/change` | Yes | No | Changes the password while logged in. | Planned |
| GET | `/users/me` | Yes | No | Returns the logged-in user's profile. | Planned |
| PATCH | `/users/me` | Yes | No | Updates the profile. | Planned |

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
