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
