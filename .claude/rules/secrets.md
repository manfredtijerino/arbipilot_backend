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
