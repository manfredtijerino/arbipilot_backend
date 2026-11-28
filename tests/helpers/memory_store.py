"""An in-memory stand-in for `database/repositories/store.py`.

It follows the same rules as the real queries, so unit tests of the login
logic need no database. The real SQL is tested by the integration tests.

What it cannot show: two requests at the same moment (row locks), and work
lost because a commit is missing. Those are covered by the integration tests
in `tests/database/`.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from database.models import (
    Order,
    PaperAccount,
    PaperFill,
    PaperPosition,
    PasswordResetCode,
    RefreshToken,
    RiskStateRow,
    User,
)
from database.repositories.errors import DuplicateRow


class MemoryUsers:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, User] = {}

    async def count(self) -> int:
        return len(self.rows)

    async def get_by_id(self, user_id: uuid.UUID, lock: bool = False) -> User | None:
        return self.rows.get(user_id)

    async def get_by_email(self, email: str, lock: bool = False) -> User | None:
        return next((u for u in self.rows.values() if u.email == email), None)

    async def add(self, user: User) -> None:
        if self.rows:  # the table allows one row
            raise DuplicateRow
        user.id = user.id or uuid.uuid4()
        user.failed_login_count = 0
        user.created_at = user.updated_at = datetime.now(UTC)
        self.rows[user.id] = user

    async def record_failed_login(
        self, user_id: uuid.UUID, now: datetime, longest_wait_seconds: int
    ) -> None:
        user = self.rows[user_id]
        wait = min(2 ** min(user.failed_login_count, 20), longest_wait_seconds)
        user.failed_login_count += 1
        user.locked_until = now + timedelta(seconds=wait)

    async def record_successful_login(self, user_id: uuid.UUID, now: datetime) -> None:
        user = self.rows[user_id]
        user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now

    async def set_password(
        self, user_id: uuid.UUID, password_hash: str, now: datetime
    ) -> None:
        user = self.rows[user_id]
        user.password_hash, user.password_changed_at = password_hash, now
        user.failed_login_count, user.locked_until = 0, None

    async def upgrade_password_hash(
        self, user_id: uuid.UUID, password_hash: str
    ) -> None:
        self.rows[user_id].password_hash = password_hash

    async def set_display_name(
        self, user_id: uuid.UUID, display_name: str | None
    ) -> User | None:
        user = self.rows.get(user_id)
        if user is not None:
            user.display_name = display_name
        return user


class MemoryTokens:
    def __init__(self) -> None:
        self.rows: list[RefreshToken] = []

    async def add(
        self, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> None:
        if any(row.token_hash == token_hash for row in self.rows):
            raise DuplicateRow
        self.rows.append(
            RefreshToken(
                id=uuid.uuid4(),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                revoked_at=None,
            )
        )

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((r for r in self.rows if r.token_hash == token_hash), None)

    async def revoke(self, token_id: uuid.UUID, now: datetime) -> bool:
        row = next(r for r in self.rows if r.id == token_id)
        if row.revoked_at is not None:
            return False
        row.revoked_at = now
        return True

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        for row in self.rows:
            if row.user_id == user_id and row.revoked_at is None:
                row.revoked_at = now

    def live(self) -> list[RefreshToken]:
        return [row for row in self.rows if row.revoked_at is None]


class MemoryCodes:
    def __init__(self) -> None:
        self.rows: list[PasswordResetCode] = []

    async def get_live(self, user_id: uuid.UUID) -> PasswordResetCode | None:
        return next(
            (r for r in self.rows if r.user_id == user_id and r.used_at is None), None
        )

    async def cancel_live(self, user_id: uuid.UUID, now: datetime) -> None:
        for row in self.rows:
            if row.user_id == user_id and row.used_at is None:
                row.used_at = now

    async def get_latest(self, user_id: uuid.UUID) -> PasswordResetCode | None:
        rows = [r for r in self.rows if r.user_id == user_id]
        return max(rows, key=lambda r: r.created_at) if rows else None

    async def count_since(self, user_id: uuid.UUID, since: datetime) -> int:
        return len(
            [r for r in self.rows if r.user_id == user_id and r.created_at > since]
        )

    async def add(
        self, user_id: uuid.UUID, code_hash: str, expires_at: datetime, now: datetime
    ) -> None:
        if await self.get_live(user_id) is not None:
            raise DuplicateRow  # the table allows one unused code per user
        self.rows.append(
            PasswordResetCode(
                id=uuid.uuid4(),
                user_id=user_id,
                code_hash=code_hash,
                expires_at=expires_at,
                attempts=0,
                used_at=None,
                created_at=now,
            )
        )

    async def add_attempt(self, code_id: uuid.UUID) -> int:
        row = next(r for r in self.rows if r.id == code_id)
        row.attempts += 1
        return row.attempts

    async def mark_used(self, code_id: uuid.UUID, now: datetime) -> bool:
        row = next(r for r in self.rows if r.id == code_id)
        if row.used_at is not None:
            return False
        row.used_at = now
        return True


def _money(value: Decimal | None) -> Decimal | None:
    """Money as the database column `Numeric(28, 8)` gives it back."""
    return None if value is None else value.quantize(Decimal("0.00000001"))


class MemoryPaper:
    """The paper account's tables, kept in plain Python objects."""

    MONEY = ("quantity", "price", "notional", "fee", "realized_pnl", "cash_after")

    def __init__(self) -> None:
        self.account: PaperAccount | None = None
        self.held: dict[str, PaperPosition] = {}
        self.filled: list[PaperFill] = []
        self.risk_state: RiskStateRow | None = None

    async def get_account(self, lock: bool = False) -> PaperAccount | None:
        return self.account

    async def create_account(self, cash: Decimal, now: datetime) -> PaperAccount:
        self.account = PaperAccount(
            id=1, cash=_money(cash), created_at=now, updated_at=now
        )
        return self.account

    async def set_cash(self, cash: Decimal, now: datetime) -> None:
        self.account.cash, self.account.updated_at = _money(cash), now

    async def positions(self) -> list[PaperPosition]:
        return [self.held[symbol] for symbol in sorted(self.held)]

    async def save_position(
        self, symbol: str, quantity: Decimal, cost: Decimal, now: datetime
    ) -> None:
        if quantity <= 0:
            self.held.pop(symbol, None)
        elif symbol in self.held:
            row = self.held[symbol]
            row.quantity, row.cost, row.updated_at = _money(quantity), _money(cost), now
        else:
            self.held[symbol] = PaperPosition(
                symbol=symbol,
                quantity=_money(quantity),
                cost=_money(cost),
                opened_at=now,
                updated_at=now,
            )

    async def add_fill(self, *, now: datetime, **fields: object) -> PaperFill:
        for name in self.MONEY:
            fields[name] = _money(fields[name])
        fill = PaperFill(id=uuid.uuid4(), created_at=now, **fields)
        self.filled.append(fill)
        return fill

    async def fill_by_id(self, fill_id: uuid.UUID) -> PaperFill | None:
        return next((f for f in self.filled if f.id == fill_id), None)

    async def fills(self, limit: int, offset: int = 0) -> list[PaperFill]:
        newest_first = list(reversed(self.filled))
        return newest_first[offset : offset + limit]

    async def get_risk_state(self) -> RiskStateRow | None:
        return self.risk_state

    async def save_risk_state(
        self,
        day: date | None,
        day_start_equity: Decimal,
        daily_pause: bool,
        outside_pause: str,
        now: datetime,
    ) -> None:
        self.risk_state = RiskStateRow(
            id=1,
            day=day,
            day_start_equity=_money(day_start_equity),
            daily_pause=daily_pause,
            outside_pause=outside_pause,
            updated_at=now,
        )


class MemoryOrders:
    """The order diary, kept in a list."""

    MONEY = ("requested_quantity", "requested_amount", "quantity", "price")

    def __init__(self) -> None:
        self.rows: list[Order] = []

    async def get_by_client_order_id(self, client_order_id: str) -> Order | None:
        return next(
            (o for o in self.rows if o.client_order_id == client_order_id), None
        )

    async def add(self, *, now: datetime, **fields: object) -> Order:
        if await self.get_by_client_order_id(fields["client_order_id"]) is not None:
            raise DuplicateRow("orders.client_order_id")
        for name in self.MONEY:
            fields[name] = _money(fields[name])
        order = Order(id=uuid.uuid4(), created_at=now, **fields)
        self.rows.append(order)
        return order

    async def newest(self, limit: int, offset: int = 0) -> list[Order]:
        newest_first = list(reversed(self.rows))
        return newest_first[offset : offset + limit]


class MemoryStore:
    def __init__(self) -> None:
        self.users = MemoryUsers()
        self.tokens = MemoryTokens()
        self.codes = MemoryCodes()
        self.paper = MemoryPaper()
        self.orders = MemoryOrders()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1
