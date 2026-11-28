"""The paper account's queries against the real test database
(`pytest -m integration`), and the whole service running on real SQL.

Few tests, many checks each: every question travels to Tokyo and back.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from config.database import session_factory
from config.decisions import parse_decisions
from config.settings import Settings
from database.repositories.errors import DuplicateRow
from database.repositories.store import Store
from services.paper_service import PaperTrading
from tests.config.test_decisions import GOOD
from tests.conftest import FakeClock
from tests.helpers.paper import ASK, live_market
from trading.risk import RiskEngine, Side

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)


def a_fill(order_id: str, now: datetime, side: str = "BUY") -> dict:
    return {
        "client_order_id": order_id,
        "symbol": "BTCUSDT",
        "side": side,
        "quantity": D("0.0004"),
        "price": D("60000"),
        "notional": D("24"),
        "fee": D("0.024"),
        "realized_pnl": None,
        "cash_after": D("275.976"),
        "risk_outcome": "approved",
        "risk_code": "ok",
        "now": now,
    }


async def test_the_paper_queries(session: AsyncSession) -> None:
    store = Store(session)
    paper = store.paper

    # The wallet: one row, exact money, 8 decimals.
    assert await paper.get_account() is None
    await paper.create_account(D("300"), NOW)
    await store.commit()
    session.expire_all()
    account = await paper.get_account(lock=True)
    assert account.cash == D("300") and str(account.cash) == "300.00000000"
    await paper.set_cash(D("276.01763759"), LATER)
    await store.commit()
    session.expire_all()
    account = await paper.get_account()
    assert (account.cash, account.updated_at) == (D("276.01763759"), LATER)

    # What is held: added, changed, and removed when nothing is left.
    assert await paper.positions() == []
    await paper.save_position("ETHUSDT", D("0.01"), D("20.02"), NOW)
    await paper.save_position("BTCUSDT", D("0.0004"), D("24.024"), NOW)
    await paper.save_position("BTCUSDT", D("0.0005"), D("29.029"), LATER)
    await store.commit()
    session.expire_all()
    btc, eth = await paper.positions()  # in the order of the name
    assert (btc.symbol, btc.quantity, btc.cost) == ("BTCUSDT", D("0.0005"), D("29.029"))
    assert (btc.opened_at, btc.updated_at) == (NOW, LATER)
    assert eth.symbol == "ETHUSDT"
    await paper.save_position("ETHUSDT", D("0"), D("0"), LATER)
    await store.commit()
    assert [p.symbol for p in await paper.positions()] == ["BTCUSDT"]

    # The fills: newest first, in pages.
    await paper.add_fill(**a_fill("order-1", NOW))
    await paper.add_fill(**a_fill("order-2", LATER, side="SELL"))
    await store.commit()
    session.expire_all()
    newest, oldest = await paper.fills(50)
    assert (newest.client_order_id, oldest.client_order_id) == ("order-2", "order-1")
    assert (newest.side, newest.fee, newest.realized_pnl) == ("SELL", D("0.024"), None)
    assert [f.client_order_id for f in await paper.fills(1, 1)] == ["order-1"]

    # The risk engine's memory: one row, rewritten in place.
    assert await paper.get_risk_state() is None
    await paper.save_risk_state(date(2026, 1, 1), D("300"), True, "", NOW)
    await paper.save_risk_state(date(2026, 1, 2), D("294.5"), False, "x" * 500, LATER)
    await store.commit()
    session.expire_all()
    state = await paper.get_risk_state()
    assert (state.day, state.day_start_equity) == (date(2026, 1, 2), D("294.5"))
    assert state.daily_pause is False and state.outside_pause == "x" * 200
    await paper.save_risk_state(None, D("0"), False, "", LATER)
    await store.commit()
    session.expire_all()
    assert (await paper.get_risk_state()).day is None


async def test_the_database_refuses_impossible_rows(session: AsyncSession) -> None:
    store = Store(session)
    await store.paper.create_account(D("300"), NOW)
    await store.paper.add_fill(**a_fill("order-1", NOW))
    await store.commit()

    async def refused(work: Callable[[], object]) -> bool:
        try:
            await work()
            await store.commit()
        except DBAPIError:
            await session.rollback()
            return True
        return False

    paper = store.paper
    # The same order written twice, an unknown side, and a negative fee.
    assert await refused(lambda: paper.add_fill(**a_fill("order-1", LATER)))
    assert await refused(lambda: paper.add_fill(**a_fill("order-2", NOW, side="HOLD")))
    bad_fee = {**a_fill("order-3", NOW), "fee": D("-1")}
    assert await refused(lambda: paper.add_fill(**bad_fee))
    # A second wallet row, and a holding with a negative cost.
    assert await refused(lambda: paper.create_account(D("1"), NOW))
    assert await refused(lambda: paper.save_position("BTCUSDT", D("1"), D("-1"), NOW))
    # Added by migration 0004: money that can never be negative.
    assert await refused(lambda: paper.set_cash(D("-0.01"), NOW))
    bad_cash = {**a_fill("order-4", NOW), "cash_after": D("-1")}
    assert await refused(lambda: paper.add_fill(**bad_cash))
    assert await refused(
        lambda: paper.save_risk_state(date(2026, 1, 1), D("-1"), False, "", NOW)
    )
    assert len(await paper.fills(50)) == 1
    assert (await paper.get_account()).cash == D("300")


def an_order(ticket: str, now: datetime, **changes: object) -> dict:
    return {
        "client_order_id": ticket,
        "mode": "shadow",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "requested_quantity": None,
        "requested_amount": D("24"),
        "status": "rejected",
        "risk_outcome": "rejected",
        "risk_code": "position_exists",
        "risk_reason": "This pair already has a position.",
        "quantity": None,
        "price": None,
        "fill_id": None,
        "now": now,
        **changes,
    }


async def test_the_order_diary_and_its_unique_ticket(session: AsyncSession) -> None:
    store = Store(session)
    await store.paper.create_account(D("300"), NOW)
    fill = await store.paper.add_fill(**a_fill("ticket-1", NOW))
    fill_id = fill.id  # read now: the row is forgotten after `expire_all`
    filled = {"status": "filled", "fill_id": fill_id, "quantity": D("0.0004")}
    await store.orders.add(**an_order("ticket-1", NOW, **filled, price=D("60000")))
    await store.orders.add(**an_order("ticket-2", LATER))
    await store.commit()
    session.expire_all()

    newest = await store.orders.newest(10)
    assert [o.client_order_id for o in newest] == ["ticket-2", "ticket-1"]
    assert [o.client_order_id for o in await store.orders.newest(1, 1)] == ["ticket-1"]
    found = await store.orders.get_by_client_order_id("ticket-1")
    assert (found.status, found.fill_id, found.quantity) == (
        "filled",
        fill_id,
        D("0.0004"),
    )
    assert (await store.paper.fill_by_id(fill_id)).client_order_id == "ticket-1"
    assert await store.orders.get_by_client_order_id("ticket-9") is None

    # The database itself refuses a second order with the same ticket.
    with pytest.raises(DuplicateRow):
        await store.orders.add(**an_order("ticket-1", LATER))
    await session.rollback()

    async def refused(**changes: object) -> bool:
        """Refused by a rule of the table, and not mistaken for a repeat."""
        try:
            await store.orders.add(**an_order("ticket-3", NOW, **changes))
            await store.commit()
        except DBAPIError:
            await session.rollback()
            return True
        return False

    assert await refused(side="HOLD")
    assert await refused(mode="margin")
    assert await refused(status="maybe")
    assert await refused(status="filled")  # "filled" without a fill
    assert await refused(fill_id=fill_id)  # a fill on a "rejected" order
    assert len(await store.orders.newest(10)) == 2


async def test_the_whole_paper_account_on_real_sql(
    test_engine: AsyncEngine,
    make_settings: Callable[..., Settings],
    fake_clock: FakeClock,  # the prices below are "now" on this clock
) -> None:
    """A buy, a restart, a sale: the same numbers as the unit tests, but
    written to and read back from PostgreSQL."""
    sessions = session_factory(test_engine)

    @asynccontextmanager
    async def open_store() -> AsyncIterator[Store]:
        async with sessions() as session:
            yield Store(session)

    assert fake_clock.now == NOW
    decisions = parse_decisions(GOOD)
    market = live_market(make_settings, NOW)

    def new_run() -> PaperTrading:
        return PaperTrading(
            decisions, RiskEngine(decisions.risk), lambda: market, open_store
        )

    before = new_run()
    bought = await before.place("BTCUSDT", Side.BUY, NOW)
    assert (bought.fill.quantity, bought.fill.price) == (D("0.0004"), D(ASK))
    assert bought.fill.cash_after == D("276.01763759")

    after = new_run()  # the app starts again: everything comes from the tables
    wallet = await after.wallet(NOW)
    assert wallet.cash == D("276.01763759") and wallet.equity == D("299.97603759")
    assert [(p.symbol, p.cost) for p in wallet.positions] == [
        ("BTCUSDT", D("23.98236241"))
    ]
    report = await after.report(NOW)
    assert (report.day, report.day_start_equity) == ("2026-01-01", D("300"))
    assert report.open_positions == 1

    # A copy of the buy's ticket that slips past the check in code (the
    # lookup is blinded here) is stopped by the database's "must be unique"
    # rule, and everything that copy wrote is thrown away with it.
    blinded = new_run()
    ticket = bought.order.client_order_id

    @asynccontextmanager
    async def blind_store() -> AsyncIterator[Store]:
        async with sessions() as session:
            store = Store(session)

            async def sees_nothing(_: str) -> None:
                return None

            store.orders.get_by_client_order_id = sees_nothing
            yield store

    blinded.open_store = blind_store
    with pytest.raises(DBAPIError):
        await blinded.place("BTCUSDT", Side.SELL, NOW, client_order_id=ticket)
    kept = await new_run().wallet(NOW)
    assert kept.cash == D("276.01763759")  # the copy's sale was not kept
    assert [p.symbol for p in kept.positions] == ["BTCUSDT"]
    assert len(await after.fills(50, 0, NOW)) == 1
    assert len(await after.orders(50, 0, NOW)) == 1

    # One second later, so "newest first" has an order to show.
    sold = await after.place("BTCUSDT", Side.SELL, NOW + timedelta(seconds=1))
    assert sold.fill.realized_pnl == D("-0.04792081")
    final = await new_run().wallet(NOW)
    assert (final.cash, final.positions) == (D("299.95207919"), [])
    assert [f.side for f in await after.fills(50, 0, NOW)] == ["SELL", "BUY"]

    # The diary has both orders, each tied to its fill by the ticket number.
    diary = await after.orders(50, 0, NOW)
    assert [(o.side, o.status) for o in diary] == [
        ("SELL", "filled"),
        ("BUY", "filled"),
    ]
    assert diary[1].client_order_id == bought.fill.client_order_id

    # The same ticket again: nothing is done twice, on real SQL.
    later = NOW + timedelta(seconds=2)
    again = await after.place(
        "BTCUSDT", Side.BUY, later, client_order_id=bought.order.client_order_id
    )
    assert again.repeated and again.fill.id == bought.fill.id
    assert len(await after.orders(50, 0, NOW)) == 2

    # The stop button: written at once, still on after a restart, then released.
    await after.kill("integration test", later)
    restarted = new_run()
    await restarted.start(later)
    status = await restarted.status(later)
    assert status.kill_switch and status.kill_reason == "integration test"
    blocked = await restarted.place("BTCUSDT", Side.BUY, later)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)
    assert (await restarted.resume(later)).kill_switch is False
    assert (await new_run().status(later)).paused is False
