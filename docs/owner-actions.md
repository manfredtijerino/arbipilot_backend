# Owner actions

What Manfred must do by hand. Claude Code announces each one with an OWNER ACTION NEEDED block when its time comes, verifies it, then marks it done here. Source: `docs/project-brief.md` §13.

## Pending

| # | Action | When | Status |
|---|---|---|---|
| 0 | Put `OBJECTIVES.md`, the context/decisions file and `docs/day0-recap.md` into the repo (or say where they are) | Before Day 2 | Pending |
| 0d | First commit on `main`, by hand (`README.md` §2.3 A) | When Step 0's checks are all confirmed | Pending |
| 0c | First push of `main` to GitHub, by hand (`README.md` §2.3) | After Steps 0 and 1 pass | Pending |
| 1 | Give Claude Code AWS access: create the limited IAM user `arbipilot-cli` and run `aws configure` (guided) | Day 1 | Pending |
| 2 | Fill the keys only he holds into the laptop's `.env`: Binance testnet key and secret, Anthropic key, Telegram token and owner ID | Day 1 | Pending |
| 3 | Create a development Telegram bot with @BotFather | Day 1 | Pending |
| 4 | Install pgAdmin and add the two connections | Day 1, after the database exists | Pending |
| 5 | Install Postman and import the collection and both environments | Day 1, and after each new endpoint | Pending |
| 6 | Copy each secret Claude Code generates from `.env` into his password manager | Each time one is generated | Recurring |
| 7 | Choose his email and password and call `POST /auth/register` from Postman | Day 2 | Pending |
| 8 | Run his Postman requests against development and say whether they pass | Before every deploy | Recurring |
| 9 | Fill the production-only keys into the server's `.env`: Binance read and trade keys, production Telegram token, Healthchecks URL | First deploy | Pending |
| 10 | Add the server's deploy key to GitHub, if Claude Code cannot do it with `gh` | First deploy | Pending |
| 11 | Open the SSH tunnel when he wants Postman to reach production | After the first deploy | Pending |
| 12 | Confirm about $300 USDT and $10 BNB are in the Binance Spot wallet | Before going live | Pending |
| 13 | Tell Claude Code to go live | After the promotion criteria are met | Pending |

## Done

| # | Action | Date | How it was verified |
|---|---|---|---|
| — | Create `.venv` (Python 3.13.7) | 2026-11-12 | `.venv/bin/python --version` |
| — | Create the GitHub repo and link the folder | 2026-11-12 | `git remote -v` shows `arbipilot_backend` (push not yet tested) |
| 0a | Git name and email for this repo (owner gave the values; Claude Code set them) | 2026-11-12 | `git config user.email` prints the personal account's email |
| 0b | Remote points at the personal GitHub account | 2026-11-12 | `git remote -v` shows `github.com-personal`; `git ls-remote origin` succeeds |
