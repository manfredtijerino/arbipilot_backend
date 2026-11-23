"""Tests for the Claude Code commit hook in `.claude/hooks/`."""

import importlib.util
from pathlib import Path

import pytest

HOOK = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "block_secret_commit.py"
)
spec = importlib.util.spec_from_file_location("block_secret_commit", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


@pytest.mark.parametrize(
    "command",
    [
        "git add a.txt && git commit -m x",
        "git stage a.txt; git commit -m x",
        "git -C . add a.txt && git commit -m x",
        "git --no-pager add a.txt",
    ],
)
def test_staging_is_detected(command):
    assert hook.STAGES_FILES.search(command)


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "feat: add login"',
        'git commit -m "docs: stage two of the plan"',
        "git status",
        "ls",
    ],
)
def test_other_commands_are_not_mistaken_for_staging(command):
    assert not hook.STAGES_FILES.search(command)


def diff_adding(path: str, line: str) -> str:
    return f"+++ b/{path}\n+{line}\n"


def test_scan_blocks_a_real_looking_value():
    fake = "abcdefghijklmnopqrstuvwxyzabcd"
    assert hook.scan(diff_adding("notes.yaml", f"API_KEY: {fake}"))


def test_scan_blocks_a_saved_postman_value():
    line = '"value": "saved-test-login-token-0001"'
    assert hook.scan(diff_adding("postman/development.postman_environment.json", line))


def test_scan_allows_ordinary_code_and_empty_keys():
    assert not hook.scan(diff_adding("config/settings.py", "jwt_secret: SecretStr"))
    assert not hook.scan(diff_adding("docs/notes.md", "JWT_SECRET="))
    assert not hook.scan(diff_adding("api/auth.py", "hashed = hash_password(raw)"))


@pytest.mark.parametrize("name", [".env", ".env.local", "keys/server.pem", "a.key"])
def test_secret_file_names_are_blocked(name):
    assert hook.BLOCKED_NAMES.search(name)


@pytest.mark.parametrize("name", ["config/environment.py", "docs/env.md"])
def test_ordinary_file_names_are_allowed(name):
    assert not hook.BLOCKED_NAMES.search(name)
