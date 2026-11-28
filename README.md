# ArbiPilot backend: my personal guide

This file reminds me of the commands and steps I do by hand: saving work, branches, running the app, and updating production.

| I want to | Go to |
|---|---|
| Continue a Claude Code chat | 1 |
| Commit, push, make a branch, merge | 2 |
| Run the app, the tests and the database changes on my laptop | 3 |
| Update the production server by hand | 4 |
| Change a `.env` value in production by hand | 5 |
| Look at the server without changing anything | 6 |

I type everything in Warp. A line starting with `#` inside a command box is a note, not a command.

1) Claude

1.1) If one chat is full of memory in Claude code, I can continue the chat in a new one like this

- /exit
- claude --continue

---

2) GitHub

Git is a notebook on my laptop that remembers every saved version of the project. GitHub is a copy of that notebook on the internet. `main` is the good version and must always work.

All commands are typed in the terminal, inside the folder `arbipilot_backend`.

2.1) Commit = save a page in the notebook (laptop only)

```
git status
git add .
git status
git commit -m "feat: login endpoint"
```

| Command | Why | Because |
|---|---|---|
| `git status` | To look at what changed | Red names are files that changed and are not chosen yet |
| `git add .` | To put all changed files in the "to save" basket | The dot means "everything in this folder" |
| `git status` (again) | **My safety check** | The names are now green. `.env` must NOT be in the list, because it holds the secret keys |
| `git commit -m "..."` | To save the basket as one page with a label | Without a commit, nothing is saved and nothing can be pushed |

- **Example message:** `feat: login endpoint` (new thing), `fix: wrong fee` (repair), `docs: update README` (documents), `chore: setup` (housekeeping).
- **A commit does not go to GitHub.** It stays on my laptop until I push.

2.2) Push = send my saved pages to GitHub

```
git push
```

- **Why:** so GitHub has a copy of my commits.
- **Because:** a commit lives only on my laptop. If the laptop breaks before a push, the work is lost.
- **Example:** I commit three times, then `git push` sends all three pages at once.
- **First push of a new branch** needs a longer command, one time only: `git push -u origin BRANCH`. The `-u` tells Git "this branch and the one on GitHub are the same thing", so after that `git push` is enough.
- **Example:** `git push -u origin feature/login`.
- **Check:** refresh the repo page on GitHub; the files are there.

2.3) Pull = bring new pages from GitHub to my laptop

```
git switch main
git pull
```

- **Why:** so my laptop's `main` is the same as GitHub's `main`.
- **Because:** when a feature is merged on GitHub, GitHub's `main` moves forward but my laptop's `main` does not know yet.
- **Example:** I merge `feature/login` on GitHub. On my laptop, `git pull` on `main` brings the login code down.
- **What I want to see:** a list of changed files, or `Already up to date.`

2.4) New branch = a separate copy to work in, made from an updated main

```
git switch main
git pull
git switch -c feature/login
```

| Command | Why | Because |
|---|---|---|
| `git switch main` | To stand on the good version | A new branch is a copy of wherever I am standing |
| `git pull` | To update `main` first | If `main` is old, my new branch starts old and misses the latest merged features |
| `git switch -c feature/login` | To create the branch and move onto it | `-c` means "create". Now my work cannot break `main` |

- **Example names:** `feature/foundation`, `feature/login`, `feature/risk-engine`.
- **Check:** `git status` says `On branch feature/login`.

2.5) The whole loop for one feature

| # | What | Command |
|---|---|---|
| 1 | Update main and make the branch | Section 2.4 |
| 2 | Claude Code builds; I test in Postman | |
| 3 | Commit | Section 2.1 |
| 4 | Send the branch to GitHub | `git push -u origin feature/login` |
| 5 | Merge into main, on GitHub | Click **Compare & pull request**, **Create pull request**, **Merge pull request** |
| 6 | Update my laptop | `git switch main` then `git pull` |
| 7 | Delete the finished branch | `git branch -d feature/login` |

- **Why step 5 is on GitHub:** the pull request page shows exactly what will change in `main` before I click Merge.
- **Only merge when tested:** tests are green and my Postman requests pass. **Because** `main` must always work.

2.6) Look around (these change nothing)

| I want to know | Command |
|---|---|
| Where am I and what is not saved? | `git status` |
| Which branches exist? | `git branch` |
| What was saved, newest first? | `git log --oneline` |
| Where does this project push to? | `git remote -v` |

2.7) Undo a small mistake

| Mistake | Fix |
|---|---|
| A file is in the basket by mistake | `git restore --staged FILE` |
| Wrong commit message (before pushing) | `git commit --amend -m "NEW MESSAGE"` |
| Anything else looks strange | Stop and ask Claude Code |

2.8) Never

- **Never** commit `.env`. **Because** GitHub is not a safe place for secret keys.
- **Never** `git push --force`. **Because** it erases pages on GitHub that cannot be brought back.
- **Never** commit directly on `main` (after the first push). **Because** `main` is the stable version.

2.9) Good to know

- This project pushes as my personal account through the address `github.com-personal` (set on 2026-11-12). Check with `git remote -v`.
- Claude Code has an automatic check that blocks secrets in its own commits. It does not see commits I type myself, so the second `git status` in 2.1 is my check.
- Error `src refspec main does not match any` means "there are no commits yet", so there is nothing to push.

---

3) My laptop (development)

All commands are typed inside the folder `arbipilot_backend`.

3.1) Start and stop the app

```
source .venv/bin/activate
lsof -iTCP:3000 -sTCP:LISTEN
python server.py
```

| Command | Why | Because |
|---|---|---|
| `source .venv/bin/activate` | To turn on the project's own Python | Without it, the libraries are not found. I see `(.venv)` at the start of the line |
| `lsof -iTCP:3000 -sTCP:LISTEN` | To check nothing is already using port 3000 | It must print **nothing**. If it prints a line, an old app is still running |
| `python server.py` | To start the app | I see lines with ✔ and `Running on port 3000` |

- **Stop the app:** press `Ctrl + C` in the Warp tab where it runs.
- **An old app is stuck on port 3000:** the `lsof` line shows a number under `PID`, for example `48213`. Then:

```
kill 48213
lsof -iTCP:3000 -sTCP:LISTEN
```

- **Why this matters:** an old app keeps answering Postman with old code. **Example:** I change something, Postman still shows the old answer, and the reason is a forgotten app.
- **Tip for Warp:** run the app in one tab and type other commands in a second tab (`Cmd + T`).

3.2) Check the code before a commit

```
ruff format .
ruff check .
pytest
```

| Command | Why | What I want to see |
|---|---|---|
| `ruff format .` | To tidy the layout of the code | `files left unchanged` or `reformatted` |
| `ruff check .` | To find mistakes in style | `All checks passed!` |
| `pytest` | To run the fast tests (no internet, no database) | `passed`, and no `failed` |
| `pytest -m integration` | To run the slow tests against the test database (about 5 minutes) | `passed` |

- **Rule:** never commit when something is red.
- **One test file only:** `pytest tests/trading/test_fees.py`.

3.3) See what is set in `.env` (never the values)

```
python scripts/env_status.py
```

- **Why:** to know which keys are filled in without showing a secret on screen.
- **Never** type `cat .env`. **Because** it prints every secret, and the screen may be shared or recorded.

3.4) Database changes (development database only)

```
alembic current
alembic upgrade head
```

| Command | Why | What I want to see |
|---|---|---|
| `alembic current` | To see which version the development tables are at | A number followed by `(head)` |
| `alembic upgrade head` | To apply new table changes | `Running upgrade ...`, or nothing when already up to date |

- **Example:** Claude Code adds a new table. I run `alembic upgrade head`, then `alembic current` shows the new number with `(head)`.
- **Never** run `alembic downgrade` without asking Claude Code first. **Because** it can delete a table with its data.

3.5) Postman

- Address: `http://localhost:3000`, environment `ArbiPilot Development`.
- A `401` answer means my token expired: I run **Log In** again.

---

4) Update production by hand

4.1) Merging into `main` does NOT update production

- **Why:** production is where real money will be one day. A change must reach it only when I say so.
- **Because:** `main` lives on GitHub and on my laptop. The server has its own copy of the code and only changes when I deploy.
- **Example:** `main` is the recipe book on the shelf. Production is the kitchen. A new recipe in the book does not change tonight's dinner until I carry it to the kitchen. That carrying is a **deploy**.

4.2) Where this stands today

- The first deploy has not happened yet. It is stage 12 of `docs/build-roadmap.md`; the Docker setup is built there.
- The commands in 4.4 to 4.7 are the plan. Claude Code confirms each one at stage 12 and corrects this file if something differs.
- Section 6 (looking at the server) works today.

4.3) Two ways to deploy

| Way | How | Good for |
|---|---|---|
| By hand | Sections 4.4 to 4.6 | When I want to do it myself and see each step |
| With Claude Code | I type `/deploy` | It runs the same steps, and I approve each server command |

- Both ways follow the same order. **Because** the order is what keeps production safe: test, tag, update, check.

4.4) Part 1, on my laptop: prove `main` is good and put a name on it

```
git switch main
git pull
git status
ruff check .
pytest
pytest -m integration
git tag release-20261205-1
git push origin release-20261205-1
```

| Command | Why | Because |
|---|---|---|
| `git switch main` then `git pull` | To stand on the newest `main` | I only deploy what is merged |
| `git status` | To check nothing is half-saved | It must say `nothing to commit, working tree clean` |
| `ruff check .`, `pytest`, `pytest -m integration` | To prove this exact version works | I never deploy on red |
| `git tag release-20261205-1` | To stick a name on this exact commit | The server must run exactly what I tested, not "whatever is newest" |
| `git push origin release-20261205-1` | To send the name to GitHub | The server fetches the tag from GitHub |

- **The tag name:** `release-` + the date (year, month, day) + `-1`. A second release on the same day ends with `-2`.
- **See my tags:** `git tag`.

4.5) Part 2, on the server: get that version and restart

```
ssh arbipilot
cd ~/arbipilot_backend
git describe --tags
git fetch --tags
git checkout release-20261205-1
docker compose run --rm app alembic upgrade head
docker compose up -d --build app
```

| Command | Why | Because |
|---|---|---|
| `ssh arbipilot` | To enter the server | The prompt changes to `ubuntu@...` |
| `cd ~/arbipilot_backend` | To go to the project folder | Every command below must run there |
| `git describe --tags` | To write down the version running **now** | I need this name if I must go back (4.7) |
| `git fetch --tags` | To download the new tag from GitHub | The server does not know it yet |
| `git checkout release-20261205-1` | To switch the code to that exact version | Never a branch, always a tag |
| `docker compose run --rm app alembic upgrade head` | To update the production tables | New code may need new tables; tables go first |
| `docker compose up -d --build app` | To rebuild and restart the app | `-d` means it keeps running after I leave |

- **A new `.env` key is needed by this version:** add it **before** the restart line, as in section 5.4.
- **Before a risky table change** (one that removes or changes a column): stop and ask Claude Code to take a database snapshot first.

4.6) Part 3, still on the server: check it worked

```
docker compose ps
docker compose logs --tail 60 app
curl -s http://127.0.0.1:3000/api/v1/health
curl -s http://127.0.0.1:3000/api/v1/health/ready
git describe --tags
docker compose run --rm app alembic current
exit
```

| Command | What I want to see |
|---|---|
| `docker compose ps` | `app` is `running` (and `healthy`) |
| `docker compose logs --tail 60 app` | The ✔ lines, `Environment: PRODUCTION`, the database `arbipilot_prod`, and the mode I expect |
| `curl ... /health` | `"environment":"production"` |
| `curl ... /health/ready` | Database, Binance, Claude and Telegram all `ok` |
| `git describe --tags` | The tag I just deployed |
| `... alembic current` | A number followed by `(head)` |
| `exit` | I am back on my laptop |

- **Also:** Telegram shows the production start message with the right mode.
- **Then:** I tell Claude Code what I deployed, so it writes the line in `docs/deploys.md`.

4.7) Going back when something is wrong

```
git checkout release-20261128-1
docker compose up -d --build app
```

- **Why:** to put the previous version back (the name I wrote down in 4.5).
- **Then** repeat the checks in 4.6.
- **Do not** undo table changes by hand. **Because** that can delete data. Ask Claude Code.

4.8) Rules for production

- **Never** edit code on the server. **Because** the next deploy erases it and nobody tested it. Fix it on the laptop, test, deploy.
- **Never** deploy a branch. Only a tag on `main`, with green tests.
- **Never** change `TRADING_MODE` to `live` as part of a deploy. That is a separate decision.
- **Never** type `sudo do-release-upgrade`. **Because** it jumps to a new Ubuntu version and can break the server.

---

5) Change a `.env` value in production by hand

5.1) What to know first

- There are two `.env` files with different values on purpose: my laptop (development) and the server (production). **Never** copy one over the other.
- The server's file is `~/arbipilot_backend/.env`. The list of every key is in `config/settings.py`.
- The app reads `.env` only when it starts. **Because** of that, a change does nothing until the app is started again.

5.2) Change a value

```
ssh arbipilot
cd ~/arbipilot_backend
nano .env
```

1. Move with the arrow keys to the line `KEY=...`.
2. Replace what is after the `=`. No spaces around the `=`, no quotes.
3. Save: `Ctrl + O`, then `Enter`. Leave: `Ctrl + X`.

Then start the app again so it reads the new value, and check:

```
docker compose up -d --force-recreate app
docker compose logs --tail 60 app
curl -s http://127.0.0.1:3000/api/v1/health/ready
exit
```

- **Why `--force-recreate`:** a plain `docker compose restart` keeps the old values. **Because** the values are given to the app when its container is created, not when it restarts.
- **A secret** (Binance key, Telegram token, Anthropic key): I copy it from my password manager straight into `nano`. I never paste it into the Claude Code chat.
- **Example:** I make a new Telegram token. I replace the line `TELEGRAM_BOT_TOKEN=...`, save, recreate the app, and the start message arrives in Telegram.

5.3) Check a key exists, without showing its value

```
grep -c '^BINANCE_API_KEY=' .env
```

- It prints `1` when the line exists and `0` when it does not.
- **Never** `cat .env`, `less .env` or `docker compose config`. **Because** they print the secrets on screen.

5.4) Add a new variable

1. A new variable always comes with code that uses it, so the code is deployed first up to `git checkout` (section 4.5).
2. `nano .env`, go to the end, add the line `NEW_KEY=value`, save.
3. Continue section 4.5 with the tables and the restart.

- **Because:** new code that does not find its key refuses to start.

5.5) Remove a variable

1. First the code must stop needing it: Claude Code removes it from `config/settings.py` on a branch, I merge, and I deploy (section 4).
2. Only after that deploy works: `nano .env`, delete the whole line (`Ctrl + K` cuts a line), save.
3. Recreate and check, as in 5.2.

- **Example of the wrong order:** I delete `SOME_KEY` first while the running code still asks for it. At the next start the app stops with an error naming the missing key.

5.6) Never

- **Never** put production keys in my laptop's `.env`.
- **Never** commit `.env`.
- **Never** set `TRADING_MODE=live` or `LIVE_CONFIRM` without having decided it on purpose.

---

6) Look at the server (these change nothing)

```
ssh arbipilot
```

| I want to know | Command | What I see |
|---|---|---|
| Since when is it running? | `uptime -s` | The date and time of the last restart |
| How much disk is free? | `df -h /` | The column `Avail` |
| How much memory is free? | `free -m` | The column `available`, in MB |
| Are updates waiting? | `apt list --upgradable` | A list, or only the word `Listing...` |
| Does it need a restart? | `ls /var/run/reboot-required` | `No such file` means no restart is needed |
| Is the app running? (after stage 12) | `docker compose ps` (inside `~/arbipilot_backend`) | `app` is `running` |
| What did the app say last? (after stage 12) | `docker compose logs --tail 60 app` | The latest log lines |
| Leave the server | `exit` | My laptop's prompt |

6.1) The spread measurement (running until 5 December 2026)

```
ssh arbipilot
cd ~/spread_measure
tail -3 measure.log
wc -l samples.csv
exit
```

| Command | What I want to see |
|---|---|
| `tail -3 measure.log` | A line per hour like `asked 120, answered 120`. Few or no `missed` lines |
| `wc -l samples.csv` | A number that grows by 9 every minute (9 coins that trade) |

- **Example:** after one full day the count is about 9 × 1,440 = 12,960 lines.
- **Do not** open `samples.csv` or delete anything in that folder. **Because** the numbers must stay untouched until they are written into the roadmap.

6.2) Reach production from Postman (after stage 12)

```
ssh -N -L 3001:127.0.0.1:3000 arbipilot
```

- **Why:** the production app listens only inside the server. This command builds a private tunnel from my laptop to it.
- **Then** Postman uses `http://localhost:3001` with the Production environment. The command prints nothing and stays open; `Ctrl + C` closes the tunnel.
