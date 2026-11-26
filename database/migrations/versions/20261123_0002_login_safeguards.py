"""login safeguards: one owner row, lowercase email, one live reset code

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The bot has one owner: a second row in users is impossible.
    op.create_index("uq_users_single_row", "users", [sa.text("(true)")], unique=True)
    op.create_check_constraint(
        op.f("ck_users_email_lowercase"), "users", "email = lower(email)"
    )
    op.create_check_constraint(
        op.f("ck_users_failed_login_count_positive"),
        "users",
        "failed_login_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_refresh_tokens_token_hash_length"),
        "refresh_tokens",
        "length(token_hash) = 64",
    )
    # At most one unused reset code per user.
    op.create_index(
        "uq_password_reset_codes_one_live",
        "password_reset_codes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )
    op.create_check_constraint(
        op.f("ck_password_reset_codes_attempts_positive"),
        "password_reset_codes",
        "attempts >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_password_reset_codes_attempts_positive"),
        "password_reset_codes",
        type_="check",
    )
    op.drop_index(
        "uq_password_reset_codes_one_live", table_name="password_reset_codes"
    )
    op.drop_constraint(
        op.f("ck_refresh_tokens_token_hash_length"), "refresh_tokens", type_="check"
    )
    op.drop_constraint(
        op.f("ck_users_failed_login_count_positive"), "users", type_="check"
    )
    op.drop_constraint(op.f("ck_users_email_lowercase"), "users", type_="check")
    op.drop_index("uq_users_single_row", table_name="users")
