"""The paper account: pretend money traded against real live prices.

It owns three jobs:

- place a pretend order, which always passes the risk engine first;
- say what the account holds and is worth right now;
- keep the wallet, the trades and the risk engine's memory in the database,
  so a restart forgets nothing.

One order is handled at a time (a lock here, and a row lock in the
database), so two orders can never spend the same cash.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from config.decisions import Decisions
from services.market_service import MarketData
from trading import paper
from trading.account import AccountSnapshot, Position
from trading.risk import (
    Decision,
    MarketView,
    OrderRequest,
    RiskEngine,
    RiskReport,
    RiskState,
    Side,
    market_view,
)

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
CENT8 = Decimal("0.00000001")  # money is kept with 8 decimals
# One piece of work may take this long before it gives up and frees the lock.
WORK_TIMEOUT_SECONDS = 30
NOT_A_NUMBER = Decimal("NaN")  # "this value is not known": the engine refuses it
SOURCE = "paper account"

# `Store` in the app, `MemoryStore` in unit tests.
OpenStore = Callable[[], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True)
class PositionView:
    symbol: str
    quantity: Decimal
    cost: Decimal  # paid for it, fees included
    price: Decimal | None  # the last known best bid; None when none is known
    price_stale: bool  # that price is missing or too old to act on
    value: Decimal | None
    profit_or_loss: Decimal | None  # value minus cost, before the selling fee
    opened_at: datetime


@dataclass(frozen=True)
class WalletView:
    cash: Decimal
    equity: Decimal | None  # None when a held pair has no known price
    prices_stale: bool  # a held pair's price is missing or too old
    positions: list[PositionView]


@dataclass(frozen=True)
class OrderResult:
    decision: Decision  # what the risk engine (or the paper broker) said
    fill: Any | None  # the saved `PaperFill`, or None when nothing was traded


def _refused(code: str, reason: str) -> Decision:
    return Decision("rejected", code, reason, ZERO, ZERO, ZERO)


class PaperTrading:
    def __init__(
        self,
        decisions: Decisions,
        engine: RiskEngine,
        market: Callable[[], MarketData],
        open_store: OpenStore,
    ) -> None:
        self._decisions = decisions
        self._engine = engine
        self._market = market
        self.open_store = open_store
        self._lock = asyncio.Lock()
        self._restored = False  # the engine got its memory back
        self._saved_state: RiskState | None = None

    # --- reading and writing the database ---

    async def _load(self, store: Any, now: datetime) -> None:
        """At the start of a run: give the risk engine back what it knew
        before the restart."""
        if not self._restored:
            row = await store.paper.get_risk_state()
            if row is not None:
                self._restore(row)
            self._restored = True

    def _restore(self, row: Any) -> None:
        state = RiskState(
            row.day, row.day_start_equity, row.daily_pause, row.outside_pause
        )
        try:
            self._engine.restore(state)
        except ValueError:
            # What was written down cannot be trusted. Open nothing until
            # the owner has looked; closing trades stays possible.
            logger.error("stored risk state unreadable: entries paused")
            self._engine.pause("the saved risk state could not be read")
            return
        logger.info("risk state restored day=%s paused=%s", row.day, row.daily_pause)
        self._saved_state = self._engine.state()

    @asynccontextmanager
    async def _work(self, now: datetime) -> AsyncIterator[Any]:
        """One piece of work: alone, on one database conversation, and saved
        at the end together with whatever the risk engine now remembers."""
        async with (
            self._lock,
            asyncio.timeout(WORK_TIMEOUT_SECONDS),
            self.open_store() as store,
        ):
            await self._load(store, now)
            yield store
            state = self._engine.state()
            changed = state != self._saved_state
            if changed:
                await store.paper.save_risk_state(
                    state.day,
                    state.day_start_equity,
                    state.daily_pause,
                    state.outside_pause,
                    now,
                )
            await store.commit()
            # Only now is it written down: a failed commit leaves it to be redone.
            if changed:
                self._saved_state = state

    async def _wallet(
        self, store: Any, now: datetime, lock: bool = False
    ) -> WalletView:
        account = await store.paper.get_account(lock=lock)
        if account is None:
            # A new database (or one reset while the app runs): the wallet
            # starts with the money from `decisions.yaml`.
            start = self._decisions.shadow.starting_equity_usdt
            account = await store.paper.create_account(start.quantize(CENT8), now)
            logger.info("paper account created with its starting balance")
        market = self._market()
        positions = []
        for row in await store.paper.positions():
            ticker = market_view(market, row.symbol).ticker
            price = ticker.bid if ticker is not None else None
            value = None
            if price is not None:
                # Rounded down to 8 decimals: never worth more than it is.
                value = (row.quantity * price).quantize(CENT8, rounding=ROUND_DOWN)
            positions.append(
                PositionView(
                    symbol=row.symbol,
                    quantity=row.quantity,
                    cost=row.cost,
                    price=price,
                    price_stale=ticker is None or price is None or ticker.stale,
                    value=value,
                    profit_or_loss=value - row.cost if value is not None else None,
                    opened_at=row.opened_at,
                )
            )
        known = all(p.value is not None for p in positions)
        held = sum((p.value for p in positions if p.value is not None), ZERO)
        return WalletView(
            cash=account.cash,
            equity=account.cash + held if known else None,
            prices_stale=any(p.price_stale for p in positions),
            positions=positions,
        )

    @staticmethod
    def _snapshot(wallet: WalletView) -> AccountSnapshot:
        """The wallet as the risk engine wants it.

        A held pair whose price is missing or too old is passed as "not a
        number". The engine then distrusts the whole account: it opens
        nothing and never takes such a reading as the day's starting point.
        The owner still sees the old value, marked as stale.
        """
        return AccountSnapshot(
            cash=wallet.cash,
            positions={
                p.symbol: Position(
                    p.symbol,
                    p.quantity,
                    NOT_A_NUMBER if p.price_stale else p.value,
                )
                for p in wallet.positions
            },
        )

    # --- what the owner sees ---

    async def report(self, now: datetime) -> RiskReport:
        """The limits and their use, for the account as it is right now."""
        async with self._work(now) as store:
            wallet = await self._wallet(store, now)
            return self._engine.report(self._snapshot(wallet), now)

    async def wallet(self, now: datetime) -> WalletView:
        async with self._work(now) as store:
            return await self._wallet(store, now)

    async def fills(self, limit: int, offset: int, now: datetime) -> list[Any]:
        """The pretend buys and sells, newest first."""
        async with self._work(now) as store:
            return await store.paper.fills(limit, offset)

    # --- placing a pretend order ---

    async def place(
        self,
        symbol: str,
        side: Side,
        now: datetime,
        quantity: Decimal | None = None,
        amount_usdt: Decimal | None = None,
    ) -> OrderResult:
        """One at-once order. A buy without a size asks for as much as the
        limits allow; a sale without a size sells everything held."""
        async with self._work(now) as store:
            wallet = await self._wallet(store, now, lock=True)
            view = market_view(self._market(), symbol)
            decision, fill = self._decide(
                symbol, side, quantity, amount_usdt, wallet, view, now
            )
            row = None
            if fill is not None:
                row = await self._record(store, symbol, decision, fill, now)
                # The account changed: let the engine see the new value now.
                after = await self._wallet(store, now)
                self._engine.report(self._snapshot(after), now)
        logger.info(
            "paper order symbol=%s side=%s outcome=%s code=%s filled=%s",
            symbol,
            side,
            decision.outcome,
            decision.code,
            fill is not None,
        )
        return OrderResult(decision, row)

    def _decide(
        self,
        symbol: str,
        side: Side,
        quantity: Decimal | None,
        amount_usdt: Decimal | None,
        wallet: WalletView,
        view: MarketView,
        now: datetime,
    ) -> tuple[Decision, paper.Fill | None]:
        rules, ticker = view.rules, view.ticker
        if rules is None:
            return _refused(
                "unknown_symbol", "This pair's trading rules are not known."
            ), None
        price = paper.fill_price(side, ticker.bid, ticker.ask) if ticker else None
        if price is None:
            return _refused(
                "price_unavailable", "No live price for this pair yet."
            ), None
        held = next((p for p in wallet.positions if p.symbol == symbol), None)
        if side is Side.SELL:
            if ticker.stale:
                # A real sale would fill at a price nobody here knows. The
                # pretend one waits for the price to come back.
                logger.warning("paper sale refused: price stale symbol=%s", symbol)
                return _refused(
                    "price_stale", "The live price is too old to act on."
                ), None
            everything = held.quantity if held else ZERO
            wanted = quantity if quantity is not None else everything
            left = everything - wanted
            if left > 0 and (
                left < rules.min_quantity or left * price < rules.min_order_value
            ):
                # What would be left is too small for Binance to ever sell:
                # sell it with the rest instead of leaving it stuck.
                wanted = everything
        elif quantity is not None:
            wanted = quantity
        else:
            wanted = (amount_usdt if amount_usdt is not None else wallet.cash) / price
        if wanted <= 0 and side is Side.SELL:
            return _refused("nothing_to_sell", "Nothing of this pair is held."), None
        if wanted <= 0:
            return _refused("cash", "There is no free cash to buy with."), None

        # Every order passes the risk engine. There is no other way to a fill.
        order = OrderRequest(symbol, side, wanted, price)
        decision = self._engine.check(order, self._snapshot(wallet), view, now)
        if not decision.allowed:
            return decision, None

        rate = self._decisions.fees.taker_pct
        holding = paper.Holding(held.quantity, held.cost) if held else None
        if side is Side.SELL:
            return decision, paper.sell(
                wallet.cash, holding, decision.quantity, decision.price, rate
            )
        fits = paper.quantity_that_fits(
            decision.quantity, decision.price, wallet.cash, rate, rules.step_size
        )
        if fits < rules.min_quantity or fits * decision.price < rules.min_order_value:
            reason = "After the fee, what the cash allows is under Binance's minimum."
            return _refused("below_minimum", reason), None
        if fits != decision.quantity:
            decision = Decision(
                "reduced",
                "cash",
                "Cut to the free cash, fee included.",
                fits,
                decision.price,
                fits * decision.price,
            )
        return decision, paper.buy(wallet.cash, holding, fits, decision.price, rate)

    @staticmethod
    async def _record(
        store: Any, symbol: str, decision: Decision, fill: paper.Fill, now: datetime
    ) -> Any:
        await store.paper.set_cash(fill.cash_after, now)
        after = fill.holding_after
        await store.paper.save_position(symbol, after.quantity, after.cost, now)
        return await store.paper.add_fill(
            client_order_id=str(uuid.uuid4()),
            symbol=symbol,
            side=str(fill.side),
            quantity=fill.quantity,
            price=fill.price,
            notional=fill.notional,
            fee=fill.fee,
            realized_pnl=fill.realized_pnl,
            cash_after=fill.cash_after,
            risk_outcome=decision.outcome,
            risk_code=decision.code,
            now=now,
        )
