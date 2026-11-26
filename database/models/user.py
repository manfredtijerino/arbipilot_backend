"""The `users` table: the owner's account. The app allows exactly one row."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # One account per email whatever the capital letters:
        # "Owner@x.test" and "owner@x.test" are the same person.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        # The bot has one owner. This index makes a second row impossible, so
        # two registration requests arriving together cannot both succeed.
        Index("uq_users_single_row", text("(true)"), unique=True),
        # Emails are stored in lowercase, so a lookup never depends on capitals.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320))
    # An Argon2 hash. The password itself is never stored anywhere.
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100))

    # Wrong passwords in a row, and until when login is locked because of them.
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Tokens issued before this moment stop working (set on every password change).
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
