#!/usr/bin/env python3
"""PostToolUse hook: format a Python file right after Claude edits it.

Formatting only. Lint fixes are left to /preflight, because auto-removing
"unused" imports in the middle of a multi-step edit deletes code that the
next edit needs. Never blocks. If ruff is not installed yet, it does nothing.
"""

import json
import os
import shutil
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path.endswith(".py") or not os.path.isfile(path):
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    venv_ruff = os.path.join(project, ".venv", "bin", "ruff")
    ruff = venv_ruff if os.path.isfile(venv_ruff) else shutil.which("ruff")
    if not ruff:
        return 0

    subprocess.run(
        [ruff, "format", "--quiet", path], cwd=project, capture_output=True, check=False
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
