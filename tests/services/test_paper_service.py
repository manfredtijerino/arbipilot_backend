"""The paper account: orders through the risk engine, fills at live prices,
everything written to the (in-memory) store, nothing forgotten by a restart."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal as D

import pytest

from config.decisions import Decisions, parse_decisions
from config.settings import Settings
from services.market_service import MarketData
from services.paper_service import PaperTrading
from tests.config.test_decisions import GOOD
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore
from tests.helpers.paper import ASK, BID, live_market, opener, set_price
from trading.risk import RiskEngine, Side

DECISIONS: Decisions = parse_decisions(GOOD)


@pytest.fixture
def market(make_settings: Callable[..., Settings], fake_clock: FakeClock) -> MarketData:
    return live_market(make_settings, fake_clock.now)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def new_run(market: MarketData, store: MemoryStore) -> tuple[PaperTrading, RiskEngine]:
    """A freshly started app: a new engine and service on the same store."""
    engine = RiskEngine(DECISIONS.risk)
    return PaperTrading(DECISIONS, engine, lambda: market, opener(store)), engine


@pytest.fixture
def paper(market: MarketData, store: MemoryStore) -> PaperTrading:
    return new_run(market, store)[0]


async def test_the_wallet_starts_with_the_money_from_decisions_yaml(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    wallet = await paper.wallet(fake_clock.now)
    assert (wallet.cash, wallet.equity, wallet.positions) == (D("300"), D("300"), [])
    assert store.paper.account.cash == D("300") and store.commits == 1
    report = await paper.report(fake_clock.now)
    assert report.equity == D("300") and report.max_position_value == D("24.00")


async def test_a_buy_is_cut_to_the_cap_filled_at_the_ask_and_charged_the_fee(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    result = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    decision, fill = result.decision, result.fill
    # 8% of 300 is 24 USDT: 0.00040 BTC at the ask of 59896.01.
    assert (decision.outcome, decision.code) == ("reduced", "position_cap")
    assert (fill.side, fill.quantity, fill.price) == ("BUY", D("0.00040"), D(ASK))
    assert fill.notional == D("23.958404")
    assert fill.fee == D("0.02395841")  # 0.1%, rounded up
    assert fill.cash_after == D("276.01763759") == store.paper.account.cash
    assert fill.realized_pnl is None and len(fill.client_order_id) == 36
    (held,) = await store.paper.positions()
    assert (held.symbol, held.quantity) == ("BTCUSDT", D("0.00040"))
    assert held.cost == D("23.98236241")
    wallet = await paper.wallet(fake_clock.now)
    (position,) = wallet.positions
    assert position.price == D(BID) and position.value == D("23.9584")
    assert position.profit_or_loss == D("23.9584") - D("23.98236241")
    assert wallet.equity == D("299.97603759")


async def test_a_smaller_order_is_approved_as_asked(
    paper: PaperTrading, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    result = await paper.place("BTCUSDT", Side.BUY, now, amount_usdt=D("12"))
    assert (result.decision.outcome, result.decision.code) == ("approved", "ok")
    assert result.fill.quantity == D("0.00020")
    part = await paper.place("BTCUSDT", Side.SELL, now, quantity=D("0.0001"))
    assert part.fill.quantity == D("0.0001")


async def test_selling_everything_returns_the_money_minus_both_fees(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    result = await paper.place("BTCUSDT", Side.SELL, fake_clock.now)
    fill = result.fill
    assert result.decision.outcome == "approved"
    assert (fill.side, fill.quantity, fill.price) == ("SELL", D("0.00040"), D(BID))
    assert fill.fee == D("0.0239584")
    assert fill.realized_pnl == D("-0.04792081")  # the spread and two fees
    assert fill.cash_after == D("299.95207919")
    assert await store.paper.positions() == []
    wallet = await paper.wallet(fake_clock.now)
    assert wallet.cash == wallet.equity == D("299.95207919")
    newest, oldest = await paper.fills(50, 0, fake_clock.now)
    assert (newest.side, oldest.side) == ("SELL", "BUY")
    assert [f.side for f in await paper.fills(1, 1, fake_clock.now)] == ["BUY"]


async def test_the_risk_engine_refuses_and_nothing_changes(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    cash = store.paper.account.cash
    second = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert second.decision.outcome == "rejected"
    assert second.decision.code == "position_exists"
    assert second.fill is None and store.paper.account.cash == cash
    assert len(store.paper.filled) == 1


@pytest.mark.parametrize(
    ("symbol", "side", "code"),
    [
        ("DOGEUSDT", Side.BUY, "unknown_symbol"),  # not on the watch list
        ("ETHUSDT", Side.BUY, "price_unavailable"),  # watched, no price yet
        ("BTCUSDT", Side.SELL, "nothing_to_sell"),  # nothing is held
    ],
)
async def test_orders_that_cannot_be_filled_are_refused(
    paper: PaperTrading,
    store: MemoryStore,
    fake_clock: FakeClock,
    symbol: str,
    side: Side,
    code: str,
) -> None:
    result = await paper.place(symbol, side, fake_clock.now)
    assert (result.decision.outcome, result.decision.code) == ("rejected", code)
    assert result.fill is None and store.paper.account.cash == D("300")


async def test_an_old_price_fills_no_sale(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    fake_clock.advance(seconds=30)  # the price is now 30 seconds old
    sale = await paper.place("BTCUSDT", Side.SELL, fake_clock.now)
    assert (sale.decision.code, sale.fill) == ("price_stale", None)
    assert len(await store.paper.positions()) == 1
    assert len(store.paper.filled) == 1


async def test_a_wallet_too_small_for_binances_minimum_buys_nothing(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.wallet(fake_clock.now)
    store.paper.account.cash = D("12")  # 8% of 12 is 0.96 USDT, under 5 USDT
    small = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (small.decision.code, small.fill) == ("below_minimum", None)


async def test_a_pause_blocks_a_buy_and_never_a_sale(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    paper, engine = new_run(market, store)
    engine.pause("test")  # the kill switch
    blocked = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)
    engine.resume()
    assert (await paper.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is not None
    engine.pause("test")  # a pause never blocks closing a trade
    assert (await paper.place("BTCUSDT", Side.SELL, fake_clock.now)).fill is not None


async def test_a_held_pair_without_a_price_makes_the_account_unreadable(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.wallet(fake_clock.now)
    await store.paper.save_position("ETHUSDT", D("0.01"), D("20"), fake_clock.now)
    wallet = await paper.wallet(fake_clock.now)
    assert wallet.equity is None and wallet.positions[0].value is None
    report = await paper.report(fake_clock.now)
    assert report.entries_paused and report.day == ""  # no day from a bad reading
    refused = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (refused.decision.code, refused.fill) == ("no_equity", None)


# --- nothing is forgotten by a restart ---


async def test_a_restart_keeps_the_wallet_and_the_open_trade(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, _ = new_run(market, store)
    await before.place("BTCUSDT", Side.BUY, fake_clock.now)
    after, _ = new_run(market, store)  # the app starts again
    wallet = await after.wallet(fake_clock.now)
    assert wallet.cash == D("276.01763759")
    held = [(p.symbol, p.quantity) for p in wallet.positions]
    assert held == [("BTCUSDT", D("0.00040"))]
    sold = await after.place("BTCUSDT", Side.SELL, fake_clock.now)
    assert sold.fill.quantity == D("0.00040")


async def test_a_restart_keeps_the_day_and_the_daily_pause(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, _ = new_run(market, store)
    await before.place("BTCUSDT", Side.BUY, fake_clock.now)
    # The price collapses: the BTC is worth far less, and the account is
    # down more than 2% (6 USDT) on the day.
    set_price(market, "BTCUSDT", "40000.00", "40000.01", fake_clock.now)
    report = await before.report(fake_clock.now)
    assert report.entries_paused and report.day_profit_or_loss < D("-6")
    saved = store.paper.risk_state
    assert (saved.daily_pause, saved.day) == (True, date(2026, 1, 1))
    assert saved.day_start_equity == D("300")

    after, engine = new_run(market, store)  # the app starts again
    # The price is back, but the pause was reached today and stays.
    set_price(market, "BTCUSDT", BID, ASK, fake_clock.now)
    report = await after.report(fake_clock.now)
    assert report.entries_paused and "2%" in report.pause_reason
    assert report.day_start_equity == D("300")
    assert engine.state().daily_pause is True

    fake_clock.advance(days=1)  # a new UTC day ends the pause
    set_price(market, "BTCUSDT", BID, ASK, fake_clock.now)
    tomorrow = await after.report(fake_clock.now)
    assert not tomorrow.entries_paused and tomorrow.day == "2026-01-02"
    saved = store.paper.risk_state
    assert (saved.daily_pause, saved.day) == (False, date(2026, 1, 2))


async def test_a_restart_keeps_an_outside_pause(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, engine = new_run(market, store)
    await before.report(fake_clock.now)
    engine.pause("stopped by the owner")
    await before.report(fake_clock.now)  # the change is written down
    after, _ = new_run(market, store)
    report = await after.report(fake_clock.now)
    assert report.entries_paused and "stopped by the owner" in report.pause_reason


async def test_the_risk_state_is_only_written_when_it_changed(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.report(fake_clock.now)
    first = store.paper.risk_state
    await paper.report(fake_clock.now)
    await paper.wallet(fake_clock.now)
    assert store.paper.risk_state is first  # not rewritten


async def test_a_fill_is_exactly_what_the_risk_engine_allowed(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    paper, engine = new_run(market, store)
    allowed = []
    real_check = engine.check

    def watching(*args: object, **kwargs: object) -> object:
        decision = real_check(*args, **kwargs)
        allowed.append(decision)
        return decision

    engine.check = watching
    bought = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    sold = await paper.place("BTCUSDT", Side.SELL, fake_clock.now)
    assert len(allowed) == 2  # one check per order, no other way to a fill
    for decision, fill in zip(allowed, (bought.fill, sold.fill), strict=True):
        assert (fill.quantity, fill.price) == (decision.quantity, decision.price)


async def test_an_old_price_opens_nothing_either(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    fake_clock.advance(seconds=30)
    buy = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (buy.decision.code, buy.fill) == ("price_stale", None)
    assert store.paper.filled == []


async def test_a_stale_price_never_becomes_the_days_starting_point(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    paper, engine = new_run(market, store)
    await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert engine.state().day == date(2026, 1, 1)
    # The stream goes quiet and midnight passes: the last price is hours old.
    fake_clock.advance(hours=13)
    report = await paper.report(fake_clock.now)
    assert report.entries_paused and "unreadable" in report.pause_reason
    assert engine.state().day == date(2026, 1, 1)  # no new day from an old price
    wallet = await paper.wallet(fake_clock.now)
    assert wallet.prices_stale and wallet.positions[0].price_stale
    assert wallet.equity is not None  # still shown to the owner, marked stale
    refused = await paper.place("ETHUSDT", Side.BUY, fake_clock.now)
    assert refused.fill is None
    # A fresh price arrives: the new day starts from a real value.
    set_price(market, "BTCUSDT", "61000.00", "61000.01", fake_clock.now)
    report = await paper.report(fake_clock.now)
    assert report.day == "2026-01-02" and not report.entries_paused
    assert report.day_start_equity == report.equity


async def test_after_a_restart_a_paused_day_still_refuses_a_buy(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, _ = new_run(market, store)
    await before.place("BTCUSDT", Side.BUY, fake_clock.now)
    set_price(market, "BTCUSDT", "40000.00", "40000.01", fake_clock.now)
    set_price(market, "ETHUSDT", "3000.00", "3000.01", fake_clock.now)
    # The loss is first noticed inside an order, not a report: it is saved too.
    noticed = await before.place("ETHUSDT", Side.BUY, fake_clock.now)
    assert noticed.fill is None
    assert store.paper.risk_state.daily_pause is True

    after, _ = new_run(market, store)  # the app starts again
    set_price(market, "BTCUSDT", BID, ASK, fake_clock.now)
    set_price(market, "ETHUSDT", "3000.00", "3000.01", fake_clock.now)
    blocked = await after.place("ETHUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("daily_loss_pause", None)
    sale = await after.place("BTCUSDT", Side.SELL, fake_clock.now)
    assert sale.fill is not None  # closing a trade is never blocked


async def test_after_a_restart_an_outside_pause_still_refuses_a_buy(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, engine = new_run(market, store)
    engine.pause("stopped by the owner")
    await before.wallet(fake_clock.now)  # any piece of work writes it down
    after, _ = new_run(market, store)
    blocked = await after.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)


async def test_an_unreadable_saved_state_pauses_instead_of_crashing(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await store.paper.save_risk_state(
        date(2026, 1, 1), D("0"), False, "", fake_clock.now
    )  # a day with no starting equity cannot be trusted
    paper, _ = new_run(market, store)
    report = await paper.report(fake_clock.now)
    assert report.entries_paused and "could not be read" in report.pause_reason
    blocked = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)


class FailingOnce(MemoryStore):
    """A store whose first commit fails and loses what was written, the way
    a dropped connection does."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    async def commit(self) -> None:
        if self.fail:
            self.fail = False
            self.paper.account = None
            self.paper.risk_state = None
            raise OSError("the connection dropped")
        await super().commit()


async def test_a_failed_first_save_is_simply_done_again(
    market: MarketData, fake_clock: FakeClock
) -> None:
    store = FailingOnce()
    paper, _ = new_run(market, store)
    with pytest.raises(OSError, match="dropped"):
        await paper.report(fake_clock.now)
    assert store.paper.account is None
    report = await paper.report(fake_clock.now)  # the next call works
    assert report.equity == D("300")
    assert store.paper.account.cash == D("300")
    assert store.paper.risk_state.day == date(2026, 1, 1)  # written this time
    assert (await paper.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is not None


async def test_a_wallet_that_vanished_starts_again_from_the_starting_money(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.wallet(fake_clock.now)
    store.paper.account = None  # the development database was reset
    wallet = await paper.wallet(fake_clock.now)
    assert wallet.cash == D("300")


async def test_the_fee_is_left_room_for_when_cash_is_the_limit(
    paper: PaperTrading, store: MemoryStore, market: MarketData, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    await paper.wallet(now)
    # Plenty of equity in ETH, but only 19.77 USDT of free cash.
    set_price(market, "ETHUSDT", "3000.00", "3000.01", now)
    await store.paper.save_position("ETHUSDT", D("0.2"), D("600"), now)
    store.paper.account.cash = D("19.77")
    result = await paper.place("BTCUSDT", Side.BUY, now)
    # 0.00033 BTC is 19.7657 USDT, but 19.7855 with the fee: one step less.
    assert (result.decision.outcome, result.decision.code) == ("reduced", "cash")
    assert result.fill.quantity == D("0.00032")
    assert D("0") <= result.fill.cash_after < D("1")
    # With almost nothing left, the next buy is under Binance's minimum.
    await store.paper.save_position("BTCUSDT", D("0"), D("0"), now)
    # (A little more ETH keeps the account's value up, so no loss pause.)
    await store.paper.save_position("ETHUSDT", D("0.21"), D("630"), now)
    # 5.393 USDT pays for 0.00009 BTC (5.39064) but not for its fee as well,
    # and one step less is 4.79 USDT: under the 5 USDT minimum.
    store.paper.account.cash = D("5.393")
    small = await paper.place("BTCUSDT", Side.BUY, now)
    assert (small.decision.code, small.fill) == ("below_minimum", None)
    assert "After the fee" in small.decision.reason
    store.paper.account.cash = D("0")
    assert (await paper.place("BTCUSDT", Side.BUY, now)).decision.code == "cash"


async def test_a_partial_sale_never_leaves_an_unsellable_rest(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    await paper.place("BTCUSDT", Side.BUY, now)  # 0.00040 BTC, about 24 USDT
    # Selling 0.00035 would leave 0.00005 BTC, about 3 USDT: under the 5 USDT
    # minimum, so it could never be sold. Everything is sold instead.
    result = await paper.place("BTCUSDT", Side.SELL, now, quantity=D("0.00035"))
    assert result.fill.quantity == D("0.00040")
    assert await store.paper.positions() == []
    # A rest that can still be sold is left alone.
    await paper.place("BTCUSDT", Side.BUY, now)
    half = await paper.place("BTCUSDT", Side.SELL, now, quantity=D("0.0002"))
    assert half.fill.quantity == D("0.0002")
    assert (await store.paper.positions())[0].quantity == D("0.0002")
