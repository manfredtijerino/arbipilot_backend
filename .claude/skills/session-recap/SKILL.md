---
name: session-recap
description: Write the end-of-session recap file so the next session can continue where this one stopped.
disable-model-invocation: true
argument-hint: [session-number]
---

# Session recap

Write `docs/session-$ARGUMENTS-recap.md`. If no number was given, use the next number after the latest recap in `docs/`.

Use exactly these sections:

1. **What was built** — files created or changed, one line each.
2. **Endpoints** — endpoints added or changed, and whether each has a test and a Postman request.
3. **Decisions made** — each decision, who made it (owner or Claude Code), and why.
4. **Open questions** — anything still waiting on the owner, including unanswered items from `docs/project-brief.md` §17.
5. **Test status** — the result of `/preflight` right now.
6. **Environments** — what is running in development and in production, and which commit production is on.
7. **Known problems** — bugs, shortcuts or TODOs left in the code, with file paths.
8. **Next session** — the first three tasks, in order.
9. **Owner actions** — every pending item from `docs/owner-actions.md`, repeated in full.

Then:

- Update `CLAUDE.md` if a command, folder or rule changed this session. Keep it under 200 lines and remove anything that is no longer true.
- Update `docs/api.md` and `docs/owner-actions.md` if they are behind.
- Run `/preflight`. If it is green, commit with the message `docs: session $ARGUMENTS recap`.
- Tell the owner in plain language what was done and what he should do next.

Never include a secret, a key or a full connection string in the recap.
