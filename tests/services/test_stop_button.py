"""The stop button, the order diary and ticket numbers (stage 8, part A).

Everything runs on the in-memory store with prices set by hand.
"""

from collections.abc import Callable
from decimal import Decimal as D

import pytest

from config.decisions import Decisions, parse_decisions
from config.settings import Settings
from database.repositories.errors import DuplicateRow
from services.market_service import MarketData
from services.paper_service import DEFAULT_KILL_REASON, PaperTrading
from tests.config.test_decisions import GOOD
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore
from tests.helpers.paper import ASK, BID, live_market, opener, set_price
from trading import router
from trading.risk import RiskEngine, Side

DECISIONS: Decisions = parse_decisions(GOOD)


@pytest.fixture
def market(make_settings: Callable[..., Settings], fake_clock: FakeClock) -> MarketData:
    market = live_market(make_settings, fake_clock.now)
    set_price(market, "ETHUSDT", "3000.00", "3000.01", fake_clock.now)
    return market


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def new_run(
    market: MarketData, store: MemoryStore, mode: str = "shadow"
) -> tuple[PaperTrading, RiskEngine]:
    """A freshly started app: a new engine and service on the same store."""
    engine = RiskEngine(DECISIONS.risk)
    service = PaperTrading(DECISIONS, engine, lambda: market, opener(store), mode=mode)
    return service, engine


@pytest.fixture
def paper(market: MarketData, store: MemoryStore) -> PaperTrading:
    return new_run(market, store)[0]


# --- the router ---


def test_only_shadow_orders_have_a_road() -> None:
    assert router.destination("shadow") is router.Destination.PAPER
    assert router.destination("testnet") is None
    assert router.destination("live") is None
    assert router.destination("anything else") is None


@pytest.mark.parametrize("mode", ["testnet", "live"])
async def test_an_order_in_a_mode_that_is_not_built_is_refused_and_written_down(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock, mode: str
) -> None:
    paper, _ = new_run(market, store, mode=mode)
    result = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (result.decision.code, result.fill) == ("mode_not_built", None)
    assert store.paper.filled == [] and store.paper.held == {}
    (order,) = store.orders.rows
    assert (order.mode, order.status, order.risk_code) == (
        mode,
        "rejected",
        "mode_not_built",
    )


# --- the stop button ---


async def test_the_stop_button_blocks_a_buy_and_is_written_down_at_once(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    status = await paper.status(fake_clock.now)
    assert (status.paused, status.kill_switch, status.mode) == (False, False, "shadow")
    status = await paper.kill("going on holiday", fake_clock.now)
    assert status.paused and status.kill_switch
    assert status.kill_reason == "going on holiday"
    assert "going on holiday" in status.pause_reason
    # Written in the same step, not at the next piece of work.
    assert store.paper.risk_state.outside_pause == "going on holiday"
    blocked = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)


async def test_the_stop_button_has_a_default_reason_and_a_longest_one(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    assert (await paper.kill("   ", fake_clock.now)).kill_reason == DEFAULT_KILL_REASON
    long = await paper.kill("x" * 500, fake_clock.now)
    assert len(long.kill_reason) == 150
    assert len(store.paper.risk_state.outside_pause) <= 200


async def test_while_stopped_a_trade_can_still_be_closed(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    await paper.kill("", fake_clock.now)
    sale = await paper.place("BTCUSDT", Side.SELL, fake_clock.now)
    assert sale.fill is not None and store.paper.held == {}
    # And a buy of another pair is still refused.
    other = await paper.place("ETHUSDT", Side.BUY, fake_clock.now)
    assert other.decision.code == "trading_paused"


@pytest.mark.parametrize("stopped", [False, True])
async def test_a_sale_can_only_close_or_shrink_never_more_than_is_held(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock, stopped: bool
) -> None:
    now = fake_clock.now
    await paper.place("BTCUSDT", Side.BUY, now)  # holds 0.00040 BTC
    if stopped:
        await paper.kill("", now)
    # Asking to sell 1 whole BTC sells the 0.00040 that is held, no more.
    big = await paper.place("BTCUSDT", Side.SELL, now, quantity=D("1"))
    assert big.fill.quantity == D("0.00040") and big.decision.outcome == "reduced"
    assert store.paper.held == {} and store.paper.account.cash > 0
    # With nothing held, a sale is refused: there is nothing to open by selling.
    none = await paper.place("BTCUSDT", Side.SELL, now, quantity=D("1"))
    assert (none.decision.code, none.fill) == ("nothing_to_sell", None)
    never_held = await paper.place("ETHUSDT", Side.SELL, now)
    assert (never_held.decision.code, never_held.fill) == ("nothing_to_sell", None)
    assert all(row.quantity > 0 for row in store.paper.held.values())


async def test_resume_opens_trading_again(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    await paper.kill("", fake_clock.now)
    status = await paper.resume(fake_clock.now)
    assert (status.paused, status.kill_switch, status.kill_reason) == (False, False, "")
    assert store.paper.risk_state.outside_pause == ""
    assert (await paper.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is not None


async def test_resume_does_not_undo_the_daily_loss_pause(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    """Two different locks: the owner's button and the 2% daily limit."""
    paper, _ = new_run(market, store)
    now = fake_clock.now
    await paper.place("BTCUSDT", Side.BUY, now)
    set_price(market, "BTCUSDT", "40000.00", "40000.01", now)  # the day loses >2%
    status = await paper.status(now)
    assert status.daily_loss_pause and status.paused and not status.kill_switch

    await paper.kill("", now)
    status = await paper.resume(now)
    assert not status.kill_switch  # the button is released...
    assert status.daily_loss_pause and status.paused  # ...the day stays paused
    assert store.paper.risk_state.daily_pause is True
    blocked = await paper.place("ETHUSDT", Side.BUY, now)
    assert (blocked.decision.code, blocked.fill) == ("daily_loss_pause", None)

    # Not after a restart either, with the price back up.
    after, _ = new_run(market, store)
    set_price(market, "BTCUSDT", BID, ASK, now)
    await after.resume(now)
    blocked = await after.place("ETHUSDT", Side.BUY, now)
    assert blocked.decision.code == "daily_loss_pause"


async def test_a_restart_stays_stopped_from_the_first_moment(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    before, _ = new_run(market, store)
    await before.kill("stop", fake_clock.now)
    after, engine = new_run(market, store)
    await after.start(fake_clock.now)  # what the app does when it starts
    assert engine.state().outside_pause == "stop"
    status = await after.status(fake_clock.now)
    assert status.paused and status.kill_reason == "stop"
    # Still stopped after a second restart; only resume opens it.
    again, _ = new_run(market, store)
    assert (await again.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is None
    await again.resume(fake_clock.now)
    last, _ = new_run(market, store)
    assert (await last.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is not None


class Flaky(MemoryStore):
    """A store whose commits can be switched off, like a lost connection."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False

    async def commit(self) -> None:
        if self.down:
            raise OSError("the connection dropped")
        await super().commit()


async def test_a_stop_that_could_not_be_saved_still_holds_and_is_saved_later(
    market: MarketData, fake_clock: FakeClock
) -> None:
    store = Flaky()
    paper, _ = new_run(market, store)
    await paper.status(fake_clock.now)
    store.down = True
    with pytest.raises(OSError, match="dropped"):
        await paper.kill("stop", fake_clock.now)
    assert store.paper.risk_state.outside_pause == "stop"  # flushed, not committed
    store.paper.risk_state.outside_pause = ""  # the database rolled it back
    store.down = False
    blocked = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)
    assert store.paper.risk_state.outside_pause == "stop"  # written this time


async def test_a_stop_pressed_before_the_first_load_is_not_overwritten_by_it(
    market: MarketData, fake_clock: FakeClock
) -> None:
    store = Flaky()
    paper, _ = new_run(market, store)
    store.down = True
    with pytest.raises(OSError):
        await paper.kill("stop", fake_clock.now)
    store.paper.risk_state = None  # nothing was kept
    store.down = False
    assert (await paper.status(fake_clock.now)).kill_switch


async def test_a_resume_that_could_not_be_saved_leaves_trading_stopped(
    market: MarketData, fake_clock: FakeClock
) -> None:
    store = Flaky()
    paper, engine = new_run(market, store)
    await paper.kill("stop", fake_clock.now)
    store.down = True
    with pytest.raises(OSError, match="dropped"):
        await paper.resume(fake_clock.now)
    assert engine.state().outside_pause == "stop"  # memory did not run ahead
    store.down = False
    assert (await paper.place("BTCUSDT", Side.BUY, fake_clock.now)).fill is None
    assert (await paper.resume(fake_clock.now)).kill_switch is False


# --- the order diary and ticket numbers ---


async def test_every_order_is_written_down_even_a_refused_one(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    bought = await paper.place("BTCUSDT", Side.BUY, now, amount_usdt=D("5000"))
    refused = await paper.place("BTCUSDT", Side.BUY, now)  # one position per pair
    unknown = await paper.place("DOGEUSDT", Side.BUY, now)
    newest = await paper.orders(10, 0, now)
    assert [o.risk_code for o in newest] == [
        "unknown_symbol",
        "position_exists",
        "position_cap",
    ]
    first = newest[2]
    assert (first.status, first.mode, first.side) == ("filled", "shadow", "BUY")
    assert first.requested_amount == D("5000") and first.requested_quantity is None
    assert (first.quantity, first.price) == (D("0.00040"), D(ASK))
    assert first.fill_id == bought.fill.id
    assert first.client_order_id == bought.fill.client_order_id
    for order, result in ((newest[1], refused), (newest[0], unknown)):
        assert (order.status, order.fill_id, order.quantity) == ("rejected", None, None)
        assert order.risk_reason == result.decision.reason
    assert [o.risk_code for o in await paper.orders(1, 1, now)] == ["position_exists"]


async def test_the_same_ticket_is_never_done_twice(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    first = await paper.place("BTCUSDT", Side.BUY, now, client_order_id="ticket-1")
    again = await paper.place("BTCUSDT", Side.BUY, now, client_order_id="ticket-1")
    assert (first.repeated, again.repeated) == (False, True)
    assert again.fill.id == first.fill.id
    assert again.decision.code == first.decision.code == "position_cap"
    assert again.order.id == first.order.id
    assert len(store.paper.filled) == len(store.orders.rows) == 1
    # A sale repeated with its ticket does not sell twice either.
    sold = await paper.place("BTCUSDT", Side.SELL, now, client_order_id="ticket-2")
    await paper.place("BTCUSDT", Side.BUY, now, client_order_id="ticket-3")
    resent = await paper.place("BTCUSDT", Side.SELL, now, client_order_id="ticket-2")
    assert resent.repeated and resent.fill.id == sold.fill.id
    assert "BTCUSDT" in store.paper.held  # the second position was not sold
    # A refused order repeated is still refused, and written down once.
    await paper.place("DOGEUSDT", Side.BUY, now, client_order_id="ticket-4")
    nope = await paper.place("DOGEUSDT", Side.BUY, now, client_order_id="ticket-4")
    assert nope.repeated and nope.fill is None
    assert nope.decision.code == "unknown_symbol"
    assert len(store.orders.rows) == 4


async def test_an_order_without_a_ticket_gets_its_own(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    one = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    two = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert not one.repeated and not two.repeated
    assert one.order.client_order_id != two.order.client_order_id
    assert len(one.order.client_order_id) == 36


async def test_when_two_copies_race_the_store_refuses_the_second(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    """The check in code can be beaten by two copies at the same moment (two
    processes). The "must be unique" rule of the store cannot."""
    now = fake_clock.now
    first = await paper.place("BTCUSDT", Side.BUY, now, client_order_id="race")
    real_lookup = store.orders.get_by_client_order_id
    blind = [True]

    async def lookup(ticket: str) -> object:
        if blind[0]:  # the second copy looked before the first was written
            blind[0] = False
            return None
        return await real_lookup(ticket)

    store.orders.get_by_client_order_id = lookup
    second = await paper.place("BTCUSDT", Side.BUY, now, client_order_id="race")
    assert second.repeated and second.order.id == first.order.id
    assert second.fill.id == first.fill.id
    # One order, one fill. (That the losing copy's own writes are thrown away
    # needs a real database: see the integration tests.)
    assert len(store.orders.rows) == len(store.paper.filled) == 1
    with pytest.raises(DuplicateRow):
        await store.orders.add(client_order_id="race", now=now)


async def test_a_ticket_used_again_for_a_different_order_is_refused(
    paper: PaperTrading, store: MemoryStore, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    await paper.place("BTCUSDT", Side.BUY, now, client_order_id="t-1")
    for symbol, side in (("BTCUSDT", Side.SELL), ("ETHUSDT", Side.BUY)):
        wrong = await paper.place(symbol, side, now, client_order_id="t-1")
        assert (wrong.decision.code, wrong.fill, wrong.repeated) == (
            "ticket_reused",
            None,
            True,
        )
    assert list(store.paper.held) == ["BTCUSDT"]  # nothing was sold or bought
    assert len(store.orders.rows) == len(store.paper.filled) == 1


class Unreachable(MemoryStore):
    """A store that cannot even be read while `down`."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False
        real = self.paper.get_risk_state

        async def get_risk_state() -> object:
            if self.down:
                raise OSError("no route to the database")
            return await real()

        self.paper.get_risk_state = get_risk_state


async def test_a_stop_pressed_while_nothing_could_be_read_survives_the_first_load(
    market: MarketData, fake_clock: FakeClock
) -> None:
    """The saved row says "not stopped". The stop was pressed while the
    database could not be read. The later load must not undo it."""
    store = Unreachable()
    earlier, _ = new_run(market, store)
    await earlier.kill("old", fake_clock.now)
    await earlier.resume(fake_clock.now)
    assert store.paper.risk_state.outside_pause == ""

    paper, engine = new_run(market, store)  # a restart; nothing loaded yet
    store.down = True
    with pytest.raises(OSError, match="no route"):
        await paper.kill("stop", fake_clock.now)
    assert engine.state().outside_pause == "stop"
    store.down = False
    blocked = await paper.place("BTCUSDT", Side.BUY, fake_clock.now)
    assert (blocked.decision.code, blocked.fill) == ("trading_paused", None)
    assert store.paper.risk_state.outside_pause == "stop"  # and written down


class AppliedThenLost(MemoryStore):
    """A commit that the database applied, while the answer never arrived."""

    def __init__(self) -> None:
        super().__init__()
        self.lose_next = False

    async def commit(self) -> None:
        await super().commit()
        if self.lose_next:
            self.lose_next = False
            raise OSError("connection reset after the commit")


async def test_a_kill_is_always_written_even_when_memory_thinks_it_was(
    market: MarketData, fake_clock: FakeClock
) -> None:
    store = AppliedThenLost()
    paper, _ = new_run(market, store)
    await paper.kill("", fake_clock.now)
    store.lose_next = True
    with pytest.raises(OSError, match="reset"):
        await paper.resume(fake_clock.now)  # the database did release the stop
    assert store.paper.risk_state.outside_pause == ""
    status = await paper.kill("", fake_clock.now)  # the owner presses again
    assert status.kill_switch
    assert store.paper.risk_state.outside_pause == DEFAULT_KILL_REASON
    restarted, _ = new_run(market, store)
    assert (await restarted.status(fake_clock.now)).kill_switch


async def test_a_stop_and_a_paused_day_both_survive_a_restart_and_resume_opens_one(
    market: MarketData, store: MemoryStore, fake_clock: FakeClock
) -> None:
    now = fake_clock.now
    before, _ = new_run(market, store)
    await before.place("BTCUSDT", Side.BUY, now)
    set_price(market, "BTCUSDT", "40000.00", "40000.01", now)
    await before.kill("stop", now)
    assert store.paper.risk_state.daily_pause is True

    after, _ = new_run(market, store)
    set_price(market, "BTCUSDT", BID, ASK, now)
    status = await after.status(now)
    assert status.kill_switch and status.daily_loss_pause
    status = await after.resume(now)
    assert not status.kill_switch and status.daily_loss_pause and status.paused
    assert (await after.place("ETHUSDT", Side.BUY, now)).decision.code == (
        "daily_loss_pause"
    )
    # While paused, a part of the position can still be sold, and all of it.
    part = await after.place("BTCUSDT", Side.SELL, now, quantity=D("0.0002"))
    assert part.fill.quantity == D("0.0002")
    rest = await after.place("BTCUSDT", Side.SELL, now, quantity=D("0.0002"))
    assert rest.fill.quantity == D("0.0002") and store.paper.held == {}
