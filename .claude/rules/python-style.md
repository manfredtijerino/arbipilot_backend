---
paths:
  - "**/*.py"
---

# Python style

- Python 3.13. Type hints on every function signature.
- Money is `Decimal`, never `float`. Build from strings: `Decimal("0.00075")`.
- Timestamps are timezone-aware UTC: `datetime.now(UTC)`. Never naive datetimes.
- I/O is async (`httpx.AsyncClient`, `asyncpg`, `websockets`). Never block the event loop with `time.sleep` or sync HTTP.
- Settings come from `config/settings.py`. Never call `os.environ` elsewhere.
- Risk values come from `config/decisions.py`. Never hard-code a limit, fee or threshold.
- `server.py` wires things together and holds no business logic. Routes in `api/` are thin; functions live in `services/`, `trading/`, `exchange/` and `ai/`.
- Every package folder has an `__init__.py` and a short `README.md` saying what belongs there.
- Catch specific exceptions. Never use a bare `except:` or swallow an error silently.
- Use `logging` with structured, single-line messages. No `print` outside the startup status lines in `server.py`.
- Import the Telegram library as `telegram`; our own package is `telegram_bot`.
- `ruff` formats and lints. Do not hand-format against it.
- Libraries are listed in the single `requirements.txt`. Never create a second requirements file, and never run `pip freeze > requirements.txt`.
