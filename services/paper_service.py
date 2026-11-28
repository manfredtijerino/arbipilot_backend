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
import unicodedata
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from config.decisions import Decisions
from database.repositories.errors import DuplicateRow
from services.market_service import MarketData
from trading import paper, router
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
DEFAULT_KILL_REASON = "stopped by the owner"
LONGEST_KILL_REASON = 150
LONGEST_REASON = 300  # the diary's column for the engine's sentence
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
    order: Any  # the saved `Order`: the diary's row for this order
    repeated: bool  # this ticket was seen before; nothing was done again


@dataclass(frozen=True)
class TradingStatus:
    """Is the bot allowed to open trades right now, and if not, why."""

    mode: str  # shadow, testnet or live
    paused: bool  # no new trade is opened right now
    pause_reason: str  # every reason, in the owner's words; "" when running
    kill_switch: bool  # the stop button is pressed
    kill_reason: str
    daily_loss_pause: bool  # today's loss limit was reached
    equity: Decimal | None  # None when a held pair has no known price
    prices_stale: bool
    open_positions: int
    day: str
    day_profit_or_loss: Decimal


def _clean(text: str) -> str:
    """Plain text on one line: no control or invisible formatting characters."""
    kept = (" " if ch.isspace() else ch for ch in text)
    return "".join(ch for ch in kept if unicodedata.category(ch)[0] != "C")


def _refused(code: str, reason: str) -> Decision:
    return Decision("rejected", code, reason, ZERO, ZERO, ZERO)


class PaperTrading:
    def __init__(
        self,
        decisions: Decisions,
        engine: RiskEngine,
        market: Callable[[], MarketData],
        open_store: OpenStore,
        mode: str = "shadow",
    ) -> None:
        self._decisions = decisions
        self._engine = engine
        self._market = market
        self.open_store = open_store
        self._mode = mode  # where the router sends approved orders
        self._pending_kill: str | None = None  # a stop not yet written down
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
            if self._pending_kill:
                self._engine.pause(self._pending_kill)
            yield store
            await self._save(store, now)

    async def _save(self, store: Any, now: datetime) -> None:
        """Write down what was done, with whatever the engine now remembers."""
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
        try:
            await store.commit()
        except BaseException:
            # Nobody knows whether the database kept it. Forget what was
            # believed saved, so the next piece of work writes it again.
            self._saved_state = None
            raise
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

    # --- the stop button ---

    async def start(self, now: datetime) -> None:
        """At startup: give the risk engine its memory back before anything
        can ask it for a trade."""
        async with self._work(now):
            pass

    async def status(self, now: datetime) -> TradingStatus:
        async with self._work(now) as store:
            return await self._status(store, now)

    async def kill(self, reason: str, now: datetime) -> TradingStatus:
        """Stop opening trades until `resume`. Closing trades stays allowed.

        The stop is written to the database in the same step. If that fails
        the stop still holds for this run, and it is written with the next
        piece of work; the caller is told it was not saved.
        """
        reason = _clean(reason)[:LONGEST_KILL_REASON].strip() or DEFAULT_KILL_REASON
        self._pending_kill = reason  # survives a failed load or a failed save
        self._engine.pause(reason)
        async with self._work(now) as store:
            self._engine.pause(reason)  # again: the load may have restored
            status = await self._status(store, now)
            self._saved_state = None  # a stop is always written, never assumed
            await self._save(store, now)
            # Written down, and still under the lock: nothing is pending.
            self._pending_kill = None
        logger.warning("kill switch pressed: entries paused")
        return status

    async def resume(self, now: datetime) -> TradingStatus:
        """Undo the stop button, and only that: a day paused by the daily
        loss limit stays paused until the next UTC day."""
        async with self._work(now) as store:
            before = self._engine.state().outside_pause
            self._engine.resume()
            try:
                status = await self._status(store, now)
                await self._save(store, now)
            except BaseException:
                # Not saved: stay stopped, so memory never runs ahead of
                # what a restart would find.
                if before:
                    self._engine.pause(before)
                raise
            # Saved, and still under the lock. A stop pressed while this
            # resume was waiting came later: it stays, and wins.
            if self._pending_kill == before:
                self._pending_kill = None
            elif self._pending_kill:
                self._engine.pause(self._pending_kill)
        logger.warning("kill switch released: entries resumed")
        return status

    async def _status(self, store: Any, now: datetime) -> TradingStatus:
        wallet = await self._wallet(store, now)
        report = self._engine.report(self._snapshot(wallet), now)
        state = self._engine.state()
        return TradingStatus(
            mode=self._mode,
            paused=report.entries_paused,
            pause_reason=report.pause_reason,
            kill_switch=bool(state.outside_pause),
            kill_reason=state.outside_pause,
            daily_loss_pause=state.daily_pause,
            equity=wallet.equity,
            prices_stale=wallet.prices_stale,
            open_positions=report.open_positions,
            day=report.day,
            day_profit_or_loss=report.day_profit_or_loss,
        )

    # --- placing an order ---

    async def orders(self, limit: int, offset: int, now: datetime) -> list[Any]:
        """The order diary, newest first."""
        async with self._work(now) as store:
            return await store.orders.newest(limit, offset)

    async def place(
        self,
        symbol: str,
        side: Side,
        now: datetime,
        quantity: Decimal | None = None,
        amount_usdt: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        """One at-once order, on the one road every order takes: asked for,
        checked by the risk engine, routed, filled, written down.

        A buy without a size asks for as much as the limits allow; a sale
        without a size sells everything held. An order whose ticket number
        (`client_order_id`) was seen before is not done again: what happened
        the first time is returned.
        """
        ticket = client_order_id or str(uuid.uuid4())
        try:
            return await self._place(symbol, side, now, quantity, amount_usdt, ticket)
        except DuplicateRow:
            # Another copy of this order was written first. The database
            # refused this one; nothing of it was kept. Show the first.
            logger.warning("order repeated: ticket seen before symbol=%s", symbol)
            async with self._work(now) as store:
                seen = await store.orders.get_by_client_order_id(ticket)
                if seen is None:
                    raise
                return await self._replay(store, seen, symbol, side)

    async def _place(
        self,
        symbol: str,
        side: Side,
        now: datetime,
        quantity: Decimal | None,
        amount_usdt: Decimal | None,
        ticket: str,
    ) -> OrderResult:
        async with self._work(now) as store:
            wallet = await self._wallet(store, now, lock=True)
            # Looked up while holding the wallet's row: a second copy of the
            # same order waits here until the first is written, then sees it.
            seen = await store.orders.get_by_client_order_id(ticket)
            if seen is not None:
                return await self._replay(store, seen, symbol, side)
            fill = None
            if router.destination(self._mode) is not router.Destination.PAPER:
                decision = _refused(
                    "mode_not_built",
                    f"Orders in {self._mode} mode are not built yet.",
                )
            else:
                view = market_view(self._market(), symbol)
                decision, fill = self._decide(
                    symbol, side, quantity, amount_usdt, wallet, view, now
                )
            row = None
            if fill is not None:
                row = await self._record(store, symbol, decision, fill, ticket, now)
                # The account changed: let the engine see the new value now.
                after = await self._wallet(store, now)
                self._engine.report(self._snapshot(after), now)
            order = await store.orders.add(
                client_order_id=ticket,
                mode=self._mode,
                symbol=symbol,
                side=str(side),
                requested_quantity=quantity,
                requested_amount=amount_usdt,
                status="filled" if row is not None else "rejected",
                risk_outcome=decision.outcome,
                risk_code=decision.code,
                risk_reason=decision.reason[:LONGEST_REASON],
                quantity=fill.quantity if fill is not None else None,
                price=fill.price if fill is not None else None,
                fill_id=row.id if row is not None else None,
                now=now,
            )
        logger.info(
            "order symbol=%s side=%s outcome=%s code=%s filled=%s",
            symbol,
            side,
            decision.outcome,
            decision.code,
            fill is not None,
        )
        return OrderResult(decision, row, order, repeated=False)

    @staticmethod
    async def _replay(store: Any, order: Any, symbol: str, side: Side) -> OrderResult:
        """What happened to an order the first time it was asked for.

        A ticket belongs to one order. Used again for a different pair or
        side it is refused, so nobody mistakes an old answer for a new trade.
        """
        if (order.symbol, order.side) != (symbol, str(side)):
            reason = "This ticket number was already used for a different order."
            return OrderResult(_refused("ticket_reused", reason), None, order, True)
        decision = Decision(
            order.risk_outcome,
            order.risk_code,
            order.risk_reason,
            order.quantity or ZERO,
            order.price or ZERO,
            (order.quantity or ZERO) * (order.price or ZERO),
        )
        fill = None
        if order.fill_id is not None:
            fill = await store.paper.fill_by_id(order.fill_id)
        return OrderResult(decision, fill, order, repeated=True)

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
        store: Any,
        symbol: str,
        decision: Decision,
        fill: paper.Fill,
        ticket: str,
        now: datetime,
    ) -> Any:
        await store.paper.set_cash(fill.cash_after, now)
        after = fill.holding_after
        await store.paper.save_position(symbol, after.quantity, after.cost, now)
        return await store.paper.add_fill(
            client_order_id=ticket,
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
