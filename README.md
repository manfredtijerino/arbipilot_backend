# this is my personal Read me file to put key comands when I want to run locally and push manually to GitHub
# This is just to remind me

1) Claude

1.1) If one chat is full of memory in Claude code, I can continue the chat in a new one like this

- /exit
- claude --continue

---

2) GitHub

**The idea in one picture.** Git is a notebook on my laptop that remembers every saved version of the project. GitHub is a copy of that notebook kept safely on the internet.

- **commit** = save a page in the notebook on my laptop.
- **push** = send my new pages to the copy on GitHub.
- **pull** = bring new pages from GitHub down to my laptop.
- **branch** = a separate copy of the notebook where I can try something without touching the good version.
- **main** = the good, stable version. It must always work.

**Who does what:** Claude Code writes the code and tells me which files are ready and a suggested message. I make the commits and the pushes myself, with the commands below.

All commands are typed in the terminal, inside the folder `arbipilot_backend`.

2.1) Already done (2026-11-12), kept as a reminder

| What | Command | Why |
|---|---|---|
| Tell Git who I am, for this project only | `git config user.name "Manfred Tijerino"` and `git config user.email "MY-PERSONAL-EMAIL"` | Every saved page is signed. No `--global`, because this laptop has two GitHub accounts and they must not mix |
| Point the project at my personal account | `git remote set-url origin git@github.com-personal:manfredtijerino/arbipilot_backend.git` | `github.com` opens the door as `manfredradix`; `github.com-personal` opens it as `manfredtijerino`, the owner of the repo |

**Check any time:** `git config user.email` and `git remote -v`.

2.2) How to make a commit (save a page)

A commit is always the same five commands, in this order.

| Step | Command | Why | What I want to see |
|---|---|---|---|
| 1. Look | `git status` | To see what changed since the last saved page | Red names = changed but not chosen yet |
| 2. Choose | `git add .` | Puts every changed file in the "to save" basket. The dot means "everything in this folder" | Nothing is printed |
| 3. Look again | `git status` | **This is my safety check.** I read the green list before saving | Green names only. **`.env` must NOT be in the list** |
| 4. Save | `git commit -m "MESSAGE"` | Saves the basket as one page, with a label | `1 file changed...` or similar |
| 5. Confirm | `git log --oneline` | To see the new page at the top of the list | My message on the first line |

- **To choose only some files** instead of everything: `git add FILE1 FILE2`. Example: `git add README.md docs/api.md`.
- **Why `.env` never shows up:** the file `.gitignore` tells Git to pretend `.env` and `.venv/` do not exist. Step 3 is me checking that this still works.
- **Before step 1,** ask Claude Code to run `/preflight`. **Because** a page should only be saved when the tests are green.
- **Important:** Claude Code has an automatic check that blocks secrets in *its own* commits. That check does not see commits I type myself. When I commit by hand, step 3 is the check.

**How to write the message:** `type: what changed`, short, in plain words.

| Type | Use it when | Example |
|---|---|---|
| `feat` | Something new works | `git commit -m "feat: login endpoint"` |
| `fix` | A bug is repaired | `git commit -m "fix: wrong fee in shadow fills"` |
| `docs` | Only documents changed | `git commit -m "docs: update README"` |
| `test` | Only tests changed | `git commit -m "test: risk engine limits"` |
| `chore` | Setup and housekeeping | `git commit -m "chore: Claude Code setup"` |

2.3) The very first commit and the very first push (only once)

**Why it is special:** GitHub is empty. A push sends commits, so there must be at least one commit first. (Pushing with zero commits gives `error: src refspec main does not match any`.)

**A. First commit, on `main`, when Step 0 is finished:**

```
git status
git add .
git status
git commit -m "chore: Claude Code setup"
git log --oneline
```

In the second `git status` I check: `.env` is not listed, `.venv` is not listed.

**B. Step 1 is built on its own branch:**

```
git switch -c feature/foundation
```

Claude Code builds Step 1 here. When its checks pass, I commit with the five commands from 2.2, for example `git commit -m "feat: project foundation"`.

**C. Bring Step 1 into `main` (on the laptop, this one time):**

```
git switch main
git merge feature/foundation
git log --oneline
```

**Why on the laptop this time:** GitHub has no `main` yet, so there is nothing there to merge into. From the next feature on, the merge happens on GitHub (see 2.4).

**D. The first push:**

```
git push -u origin main
```

**Why `-u`:** it tells Git "my `main` and GitHub's `main` are the same thing". **Because** of that, next time I only type `git push`.

**Check:** open the repo page on GitHub and refresh. The files are there.

**E. Tidy up:** `git branch -d feature/foundation`

2.4) Every new feature after that: the loop I repeat

**The rule:** never work directly on `main`. Every feature gets its own branch, made from an up-to-date `main`.

| Step | Command | Why | Example |
|---|---|---|---|
| 1. Go to main | `git switch main` | Because a new branch must start from the good version | |
| 2. Update main | `git pull` | Because main may have changed on GitHub since last time | |
| 3. Make the branch | `git switch -c feature/NAME` | A separate copy to work in, so main stays safe | `git switch -c feature/login` |
| 4. Work | Claude Code builds; I test in Postman | | |
| 5. Commit | The five commands from 2.2 | Save the work as one or more pages | `git commit -m "feat: login endpoint"` |
| 6. Send the branch | `git push -u origin feature/NAME` | A backup on GitHub, and it makes the merge possible | `git push -u origin feature/login` |
| 7. Merge into main | On GitHub: open the repo, click **Compare & pull request**, then **Create pull request**, then **Merge pull request** | Because the tested feature now becomes part of the good version, and the page shows exactly what changed | |
| 8. Update my laptop | `git switch main` then `git pull` | Because the merge happened on GitHub, my laptop's main is now behind | |
| 9. Delete the branch | `git branch -d feature/NAME` | It is finished; its work lives in main now | `git branch -d feature/login` |

**Only merge when the feature is tested:** tests are green and my Postman requests pass.

2.5) Commands to look around (they change nothing)

| I want to know | Command |
|---|---|
| Which branch am I on, and what is not saved? | `git status` |
| Which branches exist? | `git branch` |
| What was saved, newest first? | `git log --oneline` |
| What exactly did I change? | `git diff` |
| Where does this project push to? | `git remote -v` |

2.6) Small mistakes and how to undo them

| Mistake | Fix | Note |
|---|---|---|
| I added a file to the basket by mistake | `git restore --staged FILE` | The file itself is not changed, it just leaves the basket |
| I typed the wrong commit message | `git commit --amend -m "NEW MESSAGE"` | Only before pushing |
| I am on the wrong branch | `git switch BRANCH` | `git status` tells me where I am |
| Anything else looks strange | Stop and ask Claude Code | Do not guess with commands found online |

2.7) Never do these

- **Never** commit `.env`. **Because** it holds the secret keys, and GitHub is not a safe place for them.
- **Never** `git push --force`. **Because** it erases pages on GitHub that cannot be brought back.
- **Never** commit on `main` directly after the first push. **Because** main is the stable version.
