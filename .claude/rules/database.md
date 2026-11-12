---
paths:
  - "database/**"
  - "config/database.py"
  - "alembic.ini"
  - "scripts/db_*.py"
---

# Database

- PostgreSQL runs on one Lightsail managed database holding `arbipilot_dev`, `arbipilot_test` and `arbipilot_prod`. Nothing runs locally.
- Roles: `arbipilot_dev` (dev and test databases), `arbipilot_prod` (production database only), `arbipilot_readonly` (read-only on production, for the owner's pgAdmin). The master user is used only by `scripts/db_bootstrap.py`.
- All connections use TLS (`POSTGRES_SSLMODE=require` or stricter).
- Every schema change is an Alembic migration in `database/migrations/`. Never change tables by hand, in pgAdmin, or with `create_all` outside tests.
- Never edit a migration that has already been applied. Write a new one.
- A migration runs in development first. It reaches production only through `/deploy`.
- Ask the owner before any downgrade or any migration that drops or changes a table or column. Take a manual snapshot first.
- Money columns are `NUMERIC`, never floating point. Timestamps are `TIMESTAMPTZ`.
- Tables live in `database/models/`, one file per table. Queries live in `database/repositories/`. No SQL anywhere else.
- The connection URL is built in `config/settings.py` from separate `.env` values. Never log it.
- Never delete the managed database, a database or a snapshot.
- The laptop is far from Tokyo, so each development query takes a noticeable fraction of a second. Batch queries and never loop one query per row.
