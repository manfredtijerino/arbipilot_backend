"""The `password_reset_codes` table: one-time codes sent to the owner's Telegram."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"
    __table_args__ = (
        # At most one unused code per user. Asking for a new code must cancel
        # the old one first, so nobody collects fresh guesses by asking again.
        Index(
            "uq_password_reset_codes_one_live",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
        CheckConstraint("attempts >= 0", name="attempts_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # A hash of the code, never the code.
    code_hash: Mapped[str] = mapped_column(String(255))
    # Wrong guesses against this code; it is cancelled after a few.
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set the moment the code is used, so it can never be used twice.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
