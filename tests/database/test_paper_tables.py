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
    assert len(await paper.fills(50)) == 1
    assert (await paper.get_account()).cash == D("300")


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

    # One second later, so "newest first" has an order to show.
    sold = await after.place("BTCUSDT", Side.SELL, NOW + timedelta(seconds=1))
    assert sold.fill.realized_pnl == D("-0.04792081")
    final = await new_run().wallet(NOW)
    assert (final.cash, final.positions) == (D("299.95207919"), [])
    assert [f.side for f in await after.fills(50, 0, NOW)] == ["SELL", "BUY"]
