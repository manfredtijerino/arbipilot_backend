---
name: deploy
description: Release tested code from development to production. Use only when the owner asks to deploy or release.
disable-model-invocation: true
---

# Deploy to production

Stop at the first failure and tell the owner. Every `ssh`, `scp` and `aws` command waits for his approval; before each one, say what it does and what it should show.

## 1. Before leaving the laptop

1. `git status` is clean, the branch is `main`, and it matches GitHub (`git pull` reports nothing new). Every feature being released is already merged into `main`.
2. `/preflight` is green, and `pytest -m integration` passes.
3. Ask the owner: "Have your Postman requests passed against development?" Do not continue without a yes.
4. Reviews since the last release: `trading-reviewer` says SAFE TO COMMIT for any change in `trading/`, `exchange/` or `ai/`; `security-reviewer` says SAFE for any change in `api/`, `services/`, `config/` or `database/`.
5. Show the owner a release summary in plain language: the commits, new `.env` keys, new migrations, and anything that restarts. Wait for "yes, deploy".

## 2. Release

6. Tag `main` as `release-YYYYMMDD-N`, then ask the owner to push the tag (`git push origin <tag>`); he pushes by hand.
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
