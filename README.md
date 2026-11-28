# ArbiPilot backend: my personal guide

This file reminds me of the commands and steps I do by hand: saving work, branches, running the app, and updating production.

| I want to | Go to |
|---|---|
| Continue a Claude Code chat | 1 |
| Commit, push, make a branch, merge | 2 |
| Run the app and the checks on my laptop | 3 |
| Update the production server | 4 |
| Change a `.env` value in production | 5 |

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

3) Run the app on my laptop (development)

All commands are typed in the terminal, inside the folder `arbipilot_backend`.

| I want to | Command | What I should see |
|---|---|---|
| Turn on the project's Python | `source .venv/bin/activate` | `(.venv)` at the start of the line |
| Start the app | `python server.py` | Lines with ✔, and `Running on port 3000` |
| Stop the app | Press `Ctrl + C` in that terminal | The prompt comes back |
| See which `.env` keys are set (never the values) | `python scripts/env_status.py` | Each key with "set" or "empty" |
| Run the tests | `pytest` | `passed`, and no `failed` |
| Check the code style | `ruff check .` | `All checks passed!` |

- **Why stop with `Ctrl + C`:** because an app that is still running keeps port 3000, and Postman would talk to the old code.
- **Example:** I change something, forget to restart, and Postman shows the old answer. Stop, start again, test again.
- **Postman** talks to `http://localhost:3000` with the environment `ArbiPilot Development`. If I get `401`, I run **Log In** again.

---

4) Update production (the server)

4.1) Merging into `main` does NOT update production

- **Why:** production is where real money will be one day. A change must reach it only when I say so, never by accident.
- **Because:** `main` lives on GitHub and my laptop. The server has its own copy of the code and only changes when a deploy is done.
- **Example:** `main` is the recipe book on the shelf. Production is the kitchen. A new recipe in the book does not change tonight's dinner until someone carries it to the kitchen. That carrying is called a **deploy**.

4.2) The steps, from idea to production

| # | What | Who | How |
|---|---|---|---|
| 1 | Build and test the feature on a branch | Claude Code and me | Section 2.5, steps 1 to 4 |
| 2 | Merge into `main` on GitHub | Me | Section 2.5, step 5 |
| 3 | Update `main` on my laptop | Me | `git switch main` then `git pull` |
| 4 | Ask for the deploy | Me | In Claude Code I type `/deploy` |
| 5 | Checks run again; I read the summary | Claude Code | It lists the commits, new `.env` keys, table changes, and what restarts |
| 6 | I say `yes, deploy` | Me | Nothing reaches the server before this |
| 7 | Push the release tag | Me | `git push origin release-YYYYMMDD-N` (Claude Code gives me the exact line) |
| 8 | The server gets the tagged code, tables are updated, the app restarts | Claude Code | I approve each server command in the box that appears |
| 9 | Production is checked | Claude Code | It runs `/deploy-check` and shows me pass or fail for each check |
| 10 | I confirm | Me | Telegram shows the production start message with the right mode |

- **What a tag is:** a name stuck on one exact commit, like `release-20261205-1`. **Because** the server must run exactly the version that was tested, not "whatever is newest".
- **Why I approve each server command:** the box shows the command before it runs. If it is not what Claude Code described, I choose No and nothing happens.
- **If something fails after the restart:** Claude Code puts the previous tag back on the server. I do not fix anything on the server by hand.

4.3) Rules for production

- **Never** edit code on the server. **Because** the next deploy would erase it, and nobody tested it. Fix it on the laptop, test, deploy.
- **Never** deploy from a branch. Only from `main`, with green tests.
- **Never** change `TRADING_MODE` to `live` during a deploy. That is a separate decision, in my own words.

4.4) Where this stands today

- The first deploy has not happened yet. It is stage 12 of `docs/build-roadmap.md`, and the Docker setup is built there.
- Until then, the steps above are the plan, and the exact restart commands are confirmed at stage 12.

---

5) Change a `.env` value in production

5.1) What to know first

- There are two `.env` files with different values on purpose: one on my laptop (development) and one on the server (production). **Never** copy one over the other.
- The server's file is `~/arbipilot_backend/.env`.
- The list of every key is in `config/settings.py`.
- The app reads `.env` only when it starts. **Because** of that, a change does nothing until the app is restarted.

5.2) Change a value that is not a secret (for example a log level)

1. I tell Claude Code: "in production, set KEY to VALUE".
2. Claude Code shows me the server command; I approve it in the box.
3. Claude Code restarts the app and runs `/deploy-check`.
4. I see the checks pass.

5.3) Change a secret (a Binance key, the Telegram token, the Anthropic key)

- **Never paste a secret into the chat.** **Because** the chat is not a safe place for keys.
- Claude Code shows me an `OWNER ACTION NEEDED` block naming the key. Then I do it myself:

```
ssh arbipilot
nano ~/arbipilot_backend/.env
```

1. I find the line `KEY=...` and replace the value after `=` (I copy it from my password manager).
2. Save with `Ctrl + O`, then `Enter`. Leave with `Ctrl + X`.
3. I type `exit` to leave the server.
4. I tell Claude Code "done". It checks the key is set (without showing it), restarts the app and runs `/deploy-check`.

- **Example:** I make a new Binance key. I put it in the server's `.env` as above, say "done", and Claude Code confirms Binance answers.

5.4) Add a new variable

- A new variable always comes with code that uses it. So it travels with a deploy: Claude Code adds it to `config/settings.py`, to my laptop's `.env`, and to the server's `.env` during `/deploy` (step 5 of the table in 4.2 lists it).

5.5) Remove a variable

1. First the code must stop needing it. **Because** if the app still expects the key and it is gone, the app refuses to start.
2. So: Claude Code removes it from `config/settings.py` on a branch, I merge, and we deploy (section 4.2).
3. Only after that deploy works, the line is deleted from the server's `.env`, the same way as 5.2.

- **Example:** deleting `SOME_KEY` from the server first, while the running code still asks for it, would stop the app at the next restart.

5.6) Never

- **Never** run `cat .env` or anything else that prints the file on screen.
- **Never** put production keys in my laptop's `.env`.
- **Never** commit `.env`.
