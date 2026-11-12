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
