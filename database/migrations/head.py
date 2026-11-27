"""Which migration the code expects the database to be at."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@lru_cache
def latest_migration() -> str | None:
    """The newest migration in `versions/`. Reads files only; connects to nothing.

    Remembered after the first call: the files cannot change while the app runs.
    """
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
