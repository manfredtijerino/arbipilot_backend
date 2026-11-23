# this is my personal Read me file to put key comands when I want to run locally and push manually to GitHub
# This is just to remind me

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
- **Example, today:** `git push -u origin main`.
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
