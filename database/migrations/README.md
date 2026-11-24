# migrations

One file per table change, in `versions/`, applied in order by Alembic. Tables are never changed by hand.

- Apply to this machine's database: `alembic upgrade head`
- Apply to the test database (laptop only): `alembic -x target=test upgrade head`. The integration tests do this themselves.
- New migration after changing `database/models/`: `alembic revision --autogenerate --rev-id 0003 -m "<message>"` (use the next number).
- Never edit a migration that was already applied; write a new one.
- `safety.py` holds the rules: which database may be migrated, no downgrade in production.
