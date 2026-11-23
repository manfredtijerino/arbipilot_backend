#!/usr/bin/env python3
"""PreToolUse hook: stop a git commit that would include a secret.

Runs before every Bash command and only acts on `git commit`.
Exit code 2 blocks the command and shows the reason to Claude.
This is a heuristic safety net, not a guarantee.
"""

import json
import os
import re
import subprocess
import sys

BLOCKED_NAMES = re.compile(r"(^|/)\.env(\..*)?$|\.(pem|key)$")

SPECIFIC = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "login token (JWT)",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
        ),
    ),
    (
        "database URL with a password",
        re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s:/@]+:[^\s@{}$<>]{12,}@"),
    ),
]
NAME = r"[A-Za-z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD)[A-Za-z0-9_]*"
QUOTED = re.compile(rf"(?i)\b{NAME}[\"']?\s*[=:]\s*[\"'][A-Za-z0-9_\-:/+]{{24,}}[\"']")
UNQUOTED = re.compile(rf"(?i)\b{NAME}\s*[=:]\s*[A-Za-z0-9_\-:/+]{{24,}}")
# `git add` or `git stage`, also behind options such as `git -C . add`.
STAGES_FILES = re.compile(r"\bgit\s+(?:-\S+(?:\s+\S+)?\s+)*(?:add|stage)\b")
POSTMAN_ENV = re.compile(r"(^|/)postman/.*environment.*\.json$")
POSTMAN_VALUE = re.compile(r"\"value\"\s*:\s*\"(?!https?://|\{\{)[^\"]{16,}\"")


class GitFailed(Exception):
    """A git command the scan depends on did not work."""


def git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise GitFailed(" ".join(args))
    return result.stdout


def scan(diff: str) -> list[str]:
    problems: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
            continue
        if not line.startswith("+") or not current:
            continue
        added = line[1:]
        for label, pattern in SPECIFIC:
            if pattern.search(added):
                problems.append(f"{current}: looks like this secret: {label}")
        if POSTMAN_ENV.search(current) and POSTMAN_VALUE.search(added):
            problems.append(
                f"{current}: a Postman environment value is saved (leave values empty)"
            )
        if current.endswith(".py"):
            generic_hit = QUOTED.search(added)
        else:
            generic_hit = QUOTED.search(added) or UNQUOTED.search(added)
        if generic_hit:
            problems.append(
                f"{current}: a key/secret/token/password has a real-looking value"
            )
    return problems


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", command):
        return 0

    # The hook runs before the whole command. If the same command also stages
    # files, nothing is staged yet and the scan below would see nothing.
    if STAGES_FILES.search(command):
        print(
            "Commit blocked: this command stages and commits together, "
            "so the secret check cannot see the files.",
            file=sys.stderr,
        )
        print(
            "Run `git add` first, then `git commit` as a separate command.",
            file=sys.stderr,
        )
        return 2

    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    # Scan staged and unstaged changes alike: `git commit -a` and
    # `git commit <file>` both commit changes that were never staged.
    try:
        names = git(["diff", "--cached", "--name-only"], cwd).splitlines()
        diff = git(["diff", "--cached", "-U0"], cwd)
        names += git(["diff", "--name-only"], cwd).splitlines()
        diff += "\n" + git(["diff", "-U0"], cwd)
    except GitFailed as failed:
        # If the changes cannot be read, they cannot be checked: block.
        print(
            f"Commit blocked: the secret check could not read the changes "
            f"(git {failed} failed).",
            file=sys.stderr,
        )
        return 2

    problems = [
        f"{n}: secret files are never committed"
        for n in names
        if BLOCKED_NAMES.search(n)
    ]
    problems += scan(diff)
    if not problems:
        return 0

    unique = list(dict.fromkeys(problems))
    print("Commit blocked: possible secret in the commit.", file=sys.stderr)
    for problem in unique[:10]:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "Remove it (git restore --staged <file>, or delete the value), "
        "then commit again.",
        file=sys.stderr,
    )
    print(
        "Do not bypass this hook. If a real key was exposed, "
        "tell the owner to rotate it.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
