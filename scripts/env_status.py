"""Lists every `.env` key as set, empty or MISSING. Never prints a value.

Run from the project folder:  python scripts/env_status.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import dotenv_values  # noqa: E402

from config.settings import ENV_FILE, Settings, safe_key_name  # noqa: E402


def expected_keys() -> list[str]:
    """The key names, taken from the Settings class so there is one list."""
    return [name.upper() for name in Settings.model_fields]


def status_rows(env: dict[str, str | None], keys: list[str]) -> list[tuple[str, str]]:
    """One (key, status) pair per key. The status never contains a value."""
    rows: list[tuple[str, str]] = []
    for key in keys:
        if key not in env:
            rows.append((key, "MISSING"))
        elif (env[key] or "").strip():
            rows.append((key, "set"))
        else:
            rows.append((key, "empty"))
    for key in env:
        if key not in keys:
            # safe_key_name hides anything that does not look like a key name,
            # such as a secret pasted on a line of its own.
            rows.append((safe_key_name(key), "UNKNOWN (not in config/settings.py)"))
    return rows


def main(env_file: Path = ENV_FILE) -> int:
    if not env_file.is_file():
        print(".env not found in the project folder")
        return 1
    rows = status_rows(dict(dotenv_values(env_file)), expected_keys())
    width = max(len(key) for key, _ in rows)
    for key, status in rows:
        print(f"{key.ljust(width)}  {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
