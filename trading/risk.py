"""The risk engine: the one gate every order passes before it can be sent.

It answers one question per order: approved, reduced, or rejected, and why.
The limits come from `decisions.yaml` (the owner's decisions) and from
Binance's own rules for the pair. Nothing here is a guess.

Opening a trade (a BUY) is checked against everything:
  paused from outside, pair rules known and fresh, price fresh, the daily
  loss, one trade per pair, the number of open trades, the order rate, then
  the size: cut down to the position cap and to the free cash, and refused
  when what is left is under Binance's minimum.

Closing a trade (a SELL) is never blocked by those limits: when the day is
going badly, getting out must always be possible. A sale is only checked
against what is really held and against Binance's minimum.

Spot only: a BUY opens or adds, a SELL closes. There is no short selling.

What the caller must do (stages 7 and 8): build a new account snapshot for
every order, with every entry order still waiting listed in
`pending_entries` and every exit order still waiting counted in
`Position.reserved`. The engine does not remember what it approved: two
orders checked against the same old snapshot would both pass.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Literal

from config.decisions import RiskLimits
from exchange.filters import SymbolRules, ceil_to_step, floor_to_step
from services.errors import ServiceError
from services.market_service import MarketData, Ticker
from trading.account import AccountSnapshot

logger = logging.getLogger(__name__)

RATE_WINDOW = timedelta(seconds=60)
ZERO = Decimal(0)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderRequest:
    """What the strategy would like to do. The engine decides what is allowed."""

    symbol: str
    side: Side
    quantity: Decimal  # in the base asset, e.g. BTC
    price: Decimal  # the limit price, in the quote asset


@dataclass(frozen=True)
class MarketView:
    """What is known about the pair right now."""

    rules: SymbolRules | None  # None: not on the watch list, or not loaded
    rules_stale: bool
    ticker: Ticker | None  # None: no price has arrived


@dataclass(frozen=True)
class Decision:
    outcome: Literal["approved", "reduced", "rejected"]
    code: str  # a short fixed word for the reason, for records and tests
    reason: str  # a sentence for the owner
    quantity: Decimal  # what may be sent (0 when rejected)
    price: Decimal  # rounded to the pair's price step
    notional: Decimal  # quantity times price

    @property
    def allowed(self) -> bool:
        return self.outcome != "rejected"


@dataclass(frozen=True)
class RiskReport:
    """The limits and how much of each is used right now."""

    limits: RiskLimits
    equity: Decimal
    max_position_value: Decimal
    day: str  # the UTC day the daily loss is counted for
    day_start_equity: Decimal
    day_profit_or_loss: Decimal  # negative = a loss
    daily_loss_limit_value: Decimal
    entries_paused: bool
    pause_reason: str
    open_positions: int
    orders_last_minute: int


def market_view(market: MarketData, symbol: str) -> MarketView:
    """What the live market data knows about one pair, for the engine.

    Anything missing comes back as "not known", which the engine refuses.
    """
    rules, rules_stale, ticker = None, True, None
    try:
        listing = market.list_symbols()
    except ServiceError:
        pass
    else:
        rules_stale = listing.stale
        rules = next((r for r in listing.symbols if r.symbol == symbol), None)
    try:
        ticker = market.ticker(symbol)
    except ServiceError:
        pass
    return MarketView(rules=rules, rules_stale=rules_stale, ticker=ticker)


def _money(value: object) -> bool:
    return type(value) is Decimal and value.is_finite()


# Far above anything real; keeps absurd numbers out of the arithmetic.
LARGEST_NUMBER = Decimal("1000000000000")


def _equity(account: AccountSnapshot) -> Decimal | None:
    """The account's value, or None when any part of it cannot be trusted."""
    positions = list(account.positions.values())
    amounts = [
        *account.pending_entries.values(),
        *(position.quantity for position in positions),
        *(position.value for position in positions),
        *(position.reserved for position in positions),
    ]
    if not _money(account.cash) or abs(account.cash) > LARGEST_NUMBER:
        return None
    if not all(_money(amount) and 0 <= amount <= LARGEST_NUMBER for amount in amounts):
        return None
    equity = account.equity
    return equity if equity > 0 else None


def _percent(share: Decimal) -> str:
    return f"{(share * 100).normalize():f}%"


class RiskEngine:
    """Holds the limits and the little it must remember between orders.

    What it remembers lives in memory: the day's starting equity, whether the
    daily pause was reached, an outside pause, and the times of recent
    orders. Stage 7 stores the day's values in the database so a restart
    cannot forget a pause.
    """

    def __init__(self, limits: RiskLimits) -> None:
        if limits.max_positions_per_symbol != 1:
            # `account.is_open` allows one trade per pair; more needs new code.
            raise ValueError("the engine supports one position per pair")
        self._limits = limits
        self._day: date | None = None
        self._day_start_equity = ZERO
        self._daily_pause = False
        self._outside_pause = ""
        self._order_times: deque[datetime] = deque()

    @property
    def limits(self) -> RiskLimits:
        """The owner's limits. They cannot be swapped while the app runs."""
        return self._limits

    # --- a pause from outside (the kill switch, from stage 8) ---

    def pause(self, reason: str) -> None:
        """Refuse every new trade until `resume`. Closing trades stays allowed."""
        self._outside_pause = reason.strip() or "paused"
        logger.warning("entries paused from outside")

    def resume(self) -> None:
        self._outside_pause = ""

    # --- what it remembers ---

    def _observe(self, equity: Decimal, now: datetime) -> None:
        """Start a new UTC day when one began, and notice the daily loss.

        Only ever called with a trusted, positive equity: a bad reading must
        never become the day's starting point. The day only moves forward: a
        clock stepping back over midnight does not reopen yesterday.
        """
        today = now.date()
        if self._day is None or today > self._day:
            self._day, self._day_start_equity, self._daily_pause = today, equity, False
        loss = self._day_start_equity - equity
        if loss >= self._day_start_equity * self.limits.daily_loss_pause_pct:
            if not self._daily_pause:
                logger.warning("daily loss limit reached: entries paused")
            self._daily_pause = True  # stays on until the day changes

    def _recent_orders(self, now: datetime) -> int:
        while self._order_times and now - self._order_times[0] >= RATE_WINDOW:
            self._order_times.popleft()
        return len(self._order_times)

    @staticmethod
    def _utc(now: datetime) -> datetime:
        if now.tzinfo is None:
            raise ValueError("the time must carry its zone (UTC)")
        return now.astimezone(UTC)

    # --- the gate ---

    def check(
        self,
        order: OrderRequest,
        account: AccountSnapshot,
        market: MarketView,
        now: datetime,
    ) -> Decision:
        """Decide one order. An approved or reduced order uses one rate slot."""
        now = self._utc(now)
        equity = _equity(account)
        if equity is not None:
            # On every order, buy or sell, passed or refused: the day's loss
            # is watched even while entries are blocked for another reason.
            self._observe(equity, now)
        self._recent_orders(now)  # drop old order times
        try:
            decision = self._decide(order, account, equity, market, now)
        except DecimalException:
            # A number too large or too odd to calculate with.
            decision = Decision(
                "rejected",
                "invalid_order",
                "The order's numbers are not usable.",
                ZERO,
                ZERO,
                ZERO,
            )
        if decision.allowed:
            self._order_times.append(now)
        logger.info(
            "risk check symbol=%s side=%s outcome=%s code=%s",
            order.symbol if isinstance(order.symbol, str) else "?",
            order.side if isinstance(order.side, Side) else "?",
            decision.outcome,
            decision.code,
        )
        return decision

    def _decide(
        self,
        order: OrderRequest,
        account: AccountSnapshot,
        equity: Decimal | None,
        market: MarketView,
        now: datetime,
    ) -> Decision:
        def reject(code: str, reason: str) -> Decision:
            return Decision("rejected", code, reason, ZERO, ZERO, ZERO)

        if (
            not isinstance(order.side, Side)
            or not isinstance(order.symbol, str)
            or not _money(order.quantity)
            or not _money(order.price)
            or not 0 < order.quantity <= LARGEST_NUMBER
            or not 0 < order.price <= LARGEST_NUMBER
        ):
            return reject("invalid_order", "The order is not a valid buy or sell.")
        rules = market.rules
        if rules is None or rules.symbol != order.symbol:
            return reject("unknown_symbol", "This pair's trading rules are not known.")
        if order.side is Side.SELL:
            return self._decide_exit(order, account, rules, reject)

        # --- opening a trade ---
        if self._outside_pause:
            return reject(
                "trading_paused", f"Trading is paused: {self._outside_pause}."
            )
        if market.rules_stale:
            return reject("rules_stale", "The pair's trading rules are too old.")
        if not rules.trading:
            return reject("pair_not_trading", "Binance is not trading this pair now.")
        ticker = market.ticker
        if ticker is None or ticker.symbol != order.symbol:
            return reject("price_unavailable", "No live price for this pair yet.")
        if ticker.stale:
            return reject("price_stale", "The live price is too old to act on.")
        if equity is None:
            return reject("no_equity", "The account is empty or unreadable.")
        if self._daily_pause:
            return reject("daily_loss_pause", self._pause_sentence())
        if account.is_open(order.symbol):
            return reject("position_exists", "There is already a trade in this pair.")
        if len(account.open_symbols) >= self.limits.max_open_positions:
            return reject(
                "max_open_positions",
                f"{self.limits.max_open_positions} trades are already open.",
            )
        if self._recent_orders(now) >= self.limits.max_orders_per_minute:
            return reject(
                "order_rate_limit", "The order-rate limit for one minute is reached."
            )

        # --- the size ---
        price = floor_to_step(order.price, rules.tick_size)  # never pay more
        if price <= 0:
            return reject("invalid_order", "The price is under the pair's price step.")
        cap = equity * self.limits.max_position_pct_equity
        quantity = floor_to_step(order.quantity, rules.step_size)
        outcome, code, reason = "approved", "ok", "Within every limit."
        if quantity * price > cap:
            quantity = floor_to_step(cap / price, rules.step_size)
            share = _percent(self.limits.max_position_pct_equity)
            outcome, code, reason = "reduced", "position_cap", f"Cut to {share}."
        if quantity * price > account.cash:
            quantity = floor_to_step(max(account.cash, ZERO) / price, rules.step_size)
            outcome, code, reason = "reduced", "cash", "Cut to the free cash."
        notional = quantity * price
        if quantity < rules.min_quantity or notional < rules.min_order_value:
            return reject(
                "below_minimum", "What is allowed is under Binance's minimum order."
            )
        return Decision(outcome, code, reason, quantity, price, notional)  # type: ignore[arg-type]

    @staticmethod
    def _decide_exit(order, account, rules, reject) -> Decision:  # noqa: ANN001
        position = account.positions.get(order.symbol)
        if position is None or not all(
            _money(amount) and 0 <= amount <= LARGEST_NUMBER
            for amount in (position.quantity, position.reserved)
        ):
            return reject("nothing_to_sell", "Nothing of this pair is held.")
        # What is not already promised to another exit order still waiting.
        free = position.quantity - position.reserved
        if free <= 0:
            return reject("nothing_to_sell", "Nothing of this pair is free to sell.")
        price = ceil_to_step(order.price, rules.tick_size)  # never sell for less
        quantity = floor_to_step(min(order.quantity, free), rules.step_size)
        notional = quantity * price
        if quantity < rules.min_quantity or notional < rules.min_order_value:
            return reject("below_minimum", "The sale is under Binance's minimum order.")
        if order.quantity > free:
            reason = "Cut to what is held and free."
            return Decision("reduced", "holding", reason, quantity, price, notional)
        reason = "A sale of what is held."
        return Decision("approved", "ok", reason, quantity, price, notional)

    def _pause_sentence(self) -> str:
        return (
            f"The account lost {_percent(self.limits.daily_loss_pause_pct)} today; "
            "no new trade until the next UTC day."
        )

    # --- the report ---

    def report(self, account: AccountSnapshot, now: datetime) -> RiskReport:
        """The limits and their use.

        An account that cannot be read never becomes the day's starting
        point: the report then shows zero and entries as paused.
        """
        now = self._utc(now)
        equity = _equity(account)
        if equity is not None:
            self._observe(equity, now)
        reasons = []
        if self._outside_pause:
            reasons.append(f"Trading is paused: {self._outside_pause}.")
        if self._daily_pause:
            reasons.append(self._pause_sentence())
        if equity is None:
            reasons.append("The account is empty or unreadable.")
        value = equity if equity is not None else ZERO
        return RiskReport(
            limits=self.limits,
            equity=value,
            max_position_value=value * self.limits.max_position_pct_equity,
            day=self._day.isoformat() if self._day else "",
            day_start_equity=self._day_start_equity,
            day_profit_or_loss=(value - self._day_start_equity) if self._day else ZERO,
            daily_loss_limit_value=(
                self._day_start_equity * self.limits.daily_loss_pause_pct
            ),
            entries_paused=bool(reasons),
            pause_reason=" ".join(reasons),
            open_positions=len(account.open_symbols) if equity is not None else 0,
            orders_last_minute=self._recent_orders(now),
        )
