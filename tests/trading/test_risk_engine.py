"""The risk engine: every limit allowed, refused, and at its exact edge.

The owner's numbers (2026-11-27): 8% per trade, 2% daily loss, 3 trades open,
one per pair, 8 orders a minute, 300 USDT to start.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from config.decisions import RiskLimits
from exchange.filters import SymbolRules
from services.errors import MarketNotReady, UnknownSymbol
from services.market_service import SymbolsView, Ticker
from trading.account import AccountSnapshot, Position
from trading.risk import (
    MarketView,
    OrderRequest,
    RiskEngine,
    RiskState,
    Side,
    market_view,
)

NOON = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

LIMITS = RiskLimits(
    max_position_pct_equity="0.08",
    daily_loss_pause_pct="0.02",
    max_open_positions=3,
    max_positions_per_symbol=1,
    max_orders_per_minute=8,
)


def rules(symbol: str = "BTCUSDT", **changes: Any) -> SymbolRules:
    values: dict[str, Any] = {
        "symbol": symbol,
        "base_asset": symbol.removesuffix("USDT"),
        "quote_asset": "USDT",
        "status": "TRADING",
        "trading": True,
        "min_order_value": D("5.00000000"),
        "tick_size": D("0.01000000"),
        "step_size": D("0.00001000"),
        "min_quantity": D("0.00001000"),
    }
    values.update(changes)
    return SymbolRules(**values)


def ticker(symbol: str = "BTCUSDT", stale: bool = False) -> Ticker:
    return Ticker(
        symbol=symbol,
        bid=D("59999.99"),
        bid_quantity=D("1"),
        ask=D("60000.00"),
        ask_quantity=D("1"),
        last_price=D("60000.00"),
        last_quantity=D("0.01"),
        last_trade_at=NOON,
        updated_at=NOON,
        age_ms=5,
        last_trade_age_ms=5,
        stale=stale,
    )


def market(symbol: str = "BTCUSDT", **changes: Any) -> MarketView:
    values: dict[str, Any] = {
        "rules": rules(symbol),
        "rules_stale": False,
        "ticker": ticker(symbol),
    }
    values.update(changes)
    return MarketView(**values)


def account(
    cash: str = "300",
    positions: dict[str, tuple[str, str]] | None = None,
    pending: dict[str, str] | None = None,
) -> AccountSnapshot:
    return AccountSnapshot(
        cash=D(cash),
        positions={
            symbol: Position(symbol, D(quantity), D(value))
            for symbol, (quantity, value) in (positions or {}).items()
        },
        pending_entries={symbol: D(value) for symbol, value in (pending or {}).items()},
    )


def buy(usdt: str, price: str = "60000.00", symbol: str = "BTCUSDT") -> OrderRequest:
    """A buy worth about `usdt` at `price`."""
    quantity = (D(usdt) / D(price)).quantize(D("0.00000001"))
    return OrderRequest(symbol, Side.BUY, quantity, D(price))


def sell(
    quantity: str, price: str = "60000.00", symbol: str = "BTCUSDT"
) -> OrderRequest:
    return OrderRequest(symbol, Side.SELL, D(quantity), D(price))


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(LIMITS)


# --- the position cap: one trade uses at most 8% of the account ---


def test_the_roadmap_example_a_40_dollar_order_is_cut_to_24(engine: RiskEngine) -> None:
    decision = engine.check(buy("40"), account(), market(), NOON)
    assert decision.outcome == "reduced" and decision.code == "position_cap"
    assert decision.quantity == D("0.00040000")  # 24 / 60000, exactly
    assert decision.notional == D("24.0000000000")
    assert decision.notional == D("300") * D("0.08")


def test_an_order_under_the_cap_passes_untouched(engine: RiskEngine) -> None:
    decision = engine.check(buy("12"), account(), market(), NOON)
    assert decision.outcome == "approved" and decision.code == "ok"
    assert decision.quantity == D("0.00020000") and decision.notional == D("12")


def test_an_order_exactly_at_the_cap_passes_untouched(engine: RiskEngine) -> None:
    decision = engine.check(buy("24"), account(), market(), NOON)
    assert decision.outcome == "approved" and decision.notional == D("24")


def test_one_step_over_the_cap_is_cut_back_to_it(engine: RiskEngine) -> None:
    request = OrderRequest("BTCUSDT", Side.BUY, D("0.00041"), D("60000.00"))  # 24.60
    decision = engine.check(request, account(), market(), NOON)
    assert decision.outcome == "reduced" and decision.quantity == D("0.00040")


def test_the_cap_follows_the_account_not_a_fixed_number(engine: RiskEngine) -> None:
    decision = engine.check(buy("40"), account(cash="200"), market(), NOON)
    assert decision.notional <= D("16") and decision.quantity == D("0.00026")
    # 16 / 60000 = 0.000266..., rounded DOWN to the step, never up over the cap.


def test_the_account_is_cash_plus_what_is_held(engine: RiskEngine) -> None:
    held = account(cash="250", positions={"ETHUSDT": ("0.016", "50")})  # still 300
    decision = engine.check(buy("40"), held, market(), NOON)
    assert decision.notional == D("24")


def test_an_order_is_never_bigger_than_the_free_cash(engine: RiskEngine) -> None:
    rich_in_coins = account(cash="10", positions={"ETHUSDT": ("0.1", "290")})
    decision = engine.check(buy("24"), rich_in_coins, market(), NOON)
    assert decision.outcome == "reduced" and decision.code == "cash"
    assert decision.notional <= D("10") and decision.quantity == D("0.00016")


# --- the exchange's minimum order ---


def test_an_order_under_the_exchange_minimum_is_refused(engine: RiskEngine) -> None:
    decision = engine.check(buy("4.80"), account(), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "below_minimum"
    assert decision.quantity == D("0")


def test_an_order_exactly_at_the_exchange_minimum_passes(engine: RiskEngine) -> None:
    request = OrderRequest("BTCUSDT", Side.BUY, D("0.0001"), D("50000.00"))  # 5.00
    decision = engine.check(request, account(), market(), NOON)
    assert decision.outcome == "approved" and decision.notional == D("5")


def test_a_cap_that_cuts_below_the_minimum_refuses_the_order(
    engine: RiskEngine,
) -> None:
    # 8% of 50 USDT is 4 USDT: under Binance's 5 USDT minimum, so no trade at all.
    decision = engine.check(buy("40"), account(cash="50"), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "below_minimum"


def test_a_quantity_under_the_smallest_step_is_refused(engine: RiskEngine) -> None:
    view = market(rules=rules(min_quantity=D("0.001"), step_size=D("0.001")))
    decision = engine.check(buy("24"), account(), view, NOON)  # 0.0004 BTC
    assert decision.outcome == "rejected" and decision.code == "below_minimum"


def test_quantity_and_price_are_rounded_to_the_exchange_steps(
    engine: RiskEngine,
) -> None:
    request = OrderRequest("BTCUSDT", Side.BUY, D("0.000234567"), D("60000.019"))
    decision = engine.check(request, account(), market(), NOON)
    assert decision.outcome == "approved"
    assert decision.quantity == D("0.00023") and decision.price == D("60000.01")


# --- the daily-loss pause: after losing 2% in one UTC day, no new trade ---


def start_day(engine: RiskEngine, when: datetime = NOON) -> None:
    """The engine first sees the account at 300 USDT."""
    assert engine.check(buy("12"), account(), market(), when).outcome == "approved"


def test_a_loss_under_two_percent_still_trades(engine: RiskEngine) -> None:
    start_day(engine)
    decision = engine.check(buy("12"), account(cash="294.01"), market(), NOON)
    assert decision.outcome == "approved"


def test_a_loss_of_exactly_two_percent_pauses(engine: RiskEngine) -> None:
    start_day(engine)
    decision = engine.check(buy("12"), account(cash="294"), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "daily_loss_pause"


def test_the_pause_holds_for_the_day_even_if_the_account_recovers(
    engine: RiskEngine,
) -> None:
    start_day(engine)
    engine.check(buy("12"), account(cash="290"), market(), NOON)
    later = NOON + timedelta(hours=11, minutes=59)
    decision = engine.check(buy("12"), account(cash="305"), market(), later)
    assert decision.code == "daily_loss_pause"


def test_the_pause_ends_at_the_next_utc_day(engine: RiskEngine) -> None:
    start_day(engine)
    engine.check(buy("12"), account(cash="290"), market(), NOON)
    last_second = datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)
    assert engine.check(buy("12"), account(cash="290"), market(), last_second).code == (
        "daily_loss_pause"
    )
    midnight = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
    decision = engine.check(buy("12"), account(cash="290"), market(), midnight)
    assert decision.outcome == "approved"  # the new day starts from 290


def test_the_new_day_measures_its_loss_from_its_own_start(engine: RiskEngine) -> None:
    start_day(engine)
    day_two = NOON + timedelta(days=1)
    engine.check(buy("12"), account(cash="290"), market(), day_two)  # day starts at 290
    fine = engine.check(buy("12"), account(cash="284.21"), market(), day_two)
    paused = engine.check(buy("12"), account(cash="284.20"), market(), day_two)
    assert fine.outcome == "approved"
    assert paused.code == "daily_loss_pause"  # 5.80 is 2% of 290


def test_the_day_is_the_utc_day_whatever_clock_is_passed(engine: RiskEngine) -> None:
    tokyo = datetime.fromisoformat("2026-01-02T08:30:00+09:00")  # still 1 Jan in UTC
    start_day(engine)
    engine.check(buy("12"), account(cash="290"), market(), NOON)
    assert engine.check(buy("12"), account(cash="290"), market(), tokyo).code == (
        "daily_loss_pause"
    )


def test_a_time_without_a_zone_is_refused(engine: RiskEngine) -> None:
    with pytest.raises(ValueError, match="UTC"):
        engine.check(buy("12"), account(), market(), NOON.replace(tzinfo=None))


# --- how many trades may be open ---


def test_a_second_trade_in_the_same_pair_is_refused(engine: RiskEngine) -> None:
    held = account(cash="276", positions={"BTCUSDT": ("0.0004", "24")})
    decision = engine.check(buy("12"), held, market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "position_exists"


def test_an_entry_order_still_waiting_counts_as_a_trade_in_that_pair(
    engine: RiskEngine,
) -> None:
    waiting = account(cash="276", pending={"BTCUSDT": "24"})
    assert engine.check(buy("12"), waiting, market(), NOON).code == "position_exists"


def test_a_third_trade_is_allowed_and_a_fourth_is_refused(engine: RiskEngine) -> None:
    two = account(
        cash="252", positions={"ETHUSDT": ("0.008", "24")}, pending={"BNBUSDT": "24"}
    )
    assert engine.check(buy("12"), two, market(), NOON).outcome == "approved"
    three = account(
        cash="228",
        positions={"ETHUSDT": ("0.008", "24"), "SOLUSDT": ("0.1", "24")},
        pending={"BNBUSDT": "24"},
    )
    decision = engine.check(buy("12"), three, market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "max_open_positions"


def test_dust_left_from_an_old_trade_does_not_count_as_open(engine: RiskEngine) -> None:
    dust = account(cash="300", positions={"BTCUSDT": ("0", "0")})
    assert engine.check(buy("12"), dust, market(), NOON).outcome == "approved"


# --- the order-rate limit: a guard against a runaway loop ---


def test_the_eighth_order_in_a_minute_passes_and_the_ninth_is_refused(
    engine: RiskEngine,
) -> None:
    for n in range(8):
        when = NOON + timedelta(seconds=n)
        assert engine.check(buy("12"), account(), market(), when).outcome == "approved"
    ninth = engine.check(buy("12"), account(), market(), NOON + timedelta(seconds=8))
    assert ninth.outcome == "rejected" and ninth.code == "order_rate_limit"


def test_the_minute_slides_and_frees_a_slot_exactly_sixty_seconds_later(
    engine: RiskEngine,
) -> None:
    for _ in range(8):
        engine.check(buy("12"), account(), market(), NOON)
    just_before = NOON + timedelta(seconds=59, milliseconds=999)
    assert engine.check(buy("12"), account(), market(), just_before).code == (
        "order_rate_limit"
    )
    at_sixty = NOON + timedelta(seconds=60)
    assert engine.check(buy("12"), account(), market(), at_sixty).outcome == "approved"


def test_refused_orders_do_not_use_up_the_rate(engine: RiskEngine) -> None:
    for _ in range(20):
        assert engine.check(buy("1"), account(), market(), NOON).code == "below_minimum"
    assert engine.check(buy("12"), account(), market(), NOON).outcome == "approved"


# --- prices and rules that cannot be trusted ---


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"rules": None}, "unknown_symbol"),
        ({"rules_stale": True}, "rules_stale"),
        ({"rules": rules(trading=False, status="HALT")}, "pair_not_trading"),
        ({"ticker": None}, "price_unavailable"),
        ({"ticker": ticker(stale=True)}, "price_stale"),
    ],
)
def test_no_entry_without_fresh_prices_and_rules(
    engine: RiskEngine, changes: dict, code: str
) -> None:
    decision = engine.check(buy("12"), account(), market(**changes), NOON)
    assert decision.outcome == "rejected" and decision.code == code


def test_rules_for_another_pair_are_refused(engine: RiskEngine) -> None:
    decision = engine.check(buy("12"), account(), market("ETHUSDT"), NOON)
    assert decision.outcome == "rejected" and decision.code == "unknown_symbol"


def test_a_pause_from_outside_refuses_every_entry(engine: RiskEngine) -> None:
    engine.pause("kill switch")
    decision = engine.check(buy("12"), account(), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "trading_paused"
    assert "kill switch" in decision.reason
    assert engine.report(account(), NOON).entries_paused is True
    engine.resume()
    assert engine.check(buy("12"), account(), market(), NOON).outcome == "approved"


@pytest.mark.parametrize(
    "request_",
    [
        OrderRequest("BTCUSDT", Side.BUY, D("0"), D("60000")),
        OrderRequest("BTCUSDT", Side.BUY, D("-1"), D("60000")),
        OrderRequest("BTCUSDT", Side.BUY, D("0.0002"), D("0")),
        OrderRequest("BTCUSDT", Side.BUY, D("NaN"), D("60000")),
        OrderRequest("BTCUSDT", Side.BUY, D("Infinity"), D("60000")),
        OrderRequest("BTCUSDT", Side.BUY, 0.0002, D("60000")),  # a float
        OrderRequest("BTCUSDT", Side.BUY, D("0.0002"), 60000.0),
        OrderRequest("BTCUSDT", "BUY ", D("0.0002"), D("60000")),
    ],
)
def test_a_malformed_order_is_refused(
    engine: RiskEngine, request_: OrderRequest
) -> None:
    decision = engine.check(request_, account(), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "invalid_order"


@pytest.mark.parametrize("cash", ["0", "-5"])
def test_an_empty_account_opens_nothing(engine: RiskEngine, cash: str) -> None:
    decision = engine.check(buy("12"), account(cash=cash), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "no_equity"


def test_money_in_the_account_must_be_decimal(engine: RiskEngine) -> None:
    broken = AccountSnapshot(cash=300.0, positions={}, pending_entries={})
    decision = engine.check(buy("12"), broken, market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "no_equity"


# --- exits: getting out is never blocked by the entry limits ---


def held() -> AccountSnapshot:
    return account(cash="276", positions={"BTCUSDT": ("0.0004", "24")})


def test_a_sale_passes_while_entries_are_paused_for_the_day(engine: RiskEngine) -> None:
    start_day(engine)
    engine.check(buy("12", symbol="BTCUSDT"), account(cash="290"), market(), NOON)
    decision = engine.check(sell("0.0004"), held(), market(), NOON)
    assert decision.outcome == "approved" and decision.quantity == D("0.0004")


def test_a_sale_passes_on_a_stale_price_a_pause_and_a_full_minute(
    engine: RiskEngine,
) -> None:
    for _ in range(8):
        engine.check(buy("12"), account(), market(), NOON)
    view = market(ticker=ticker(stale=True), rules_stale=True)
    engine.pause("kill")
    decision = engine.check(sell("0.0004"), held(), view, NOON)
    assert decision.outcome == "approved"


def test_a_sale_is_never_bigger_than_what_is_held(engine: RiskEngine) -> None:
    decision = engine.check(sell("0.0010"), held(), market(), NOON)
    assert decision.outcome == "reduced" and decision.code == "holding"
    assert decision.quantity == D("0.0004")


def test_a_sale_of_something_not_held_is_refused(engine: RiskEngine) -> None:
    decision = engine.check(sell("0.0004"), account(), market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "nothing_to_sell"


def test_a_sale_too_small_for_the_exchange_is_refused(engine: RiskEngine) -> None:
    tiny = account(cash="299", positions={"BTCUSDT": ("0.00001", "0.6")})
    decision = engine.check(sell("0.00001"), tiny, market(), NOON)
    assert decision.outcome == "rejected" and decision.code == "below_minimum"


def test_a_sale_price_is_rounded_up_to_the_tick(engine: RiskEngine) -> None:
    decision = engine.check(sell("0.0004", price="60000.011"), held(), market(), NOON)
    assert decision.price == D("60000.02")  # never sells for less than asked


def test_a_sale_needs_the_pairs_rules(engine: RiskEngine) -> None:
    decision = engine.check(sell("0.0004"), held(), market(rules=None), NOON)
    assert decision.outcome == "rejected" and decision.code == "unknown_symbol"


# --- the report: the limits and how much of each is used ---


def test_the_report_before_any_order(engine: RiskEngine) -> None:
    report = engine.report(account(), NOON)
    assert report.equity == D("300")
    assert report.max_position_value == D("24.00")
    assert report.daily_loss_limit_value == D("6.00")
    assert report.day == "2026-01-01" and report.day_start_equity == D("300")
    assert report.day_profit_or_loss == D("0")
    assert report.entries_paused is False and report.pause_reason == ""
    assert (report.open_positions, report.orders_last_minute) == (0, 0)
    assert report.limits is LIMITS


def test_the_report_shows_what_is_used(engine: RiskEngine) -> None:
    start_day(engine)
    engine.check(buy("12"), account(), market(), NOON + timedelta(seconds=30))
    now = NOON + timedelta(seconds=70)  # the first order is over a minute old
    state = account(cash="270", positions={"BTCUSDT": ("0.0004", "24")})
    report = engine.report(state, now)
    assert report.equity == D("294") and report.day_profit_or_loss == D("-6")
    assert report.entries_paused is True
    assert "2%" in report.pause_reason
    assert (report.open_positions, report.orders_last_minute) == (1, 1)
    assert report.max_position_value == D("23.52")  # 8% of today's 294


def test_looking_at_the_report_uses_no_order_slot(engine: RiskEngine) -> None:
    for _ in range(50):
        engine.report(account(), NOON)
    assert engine.report(account(), NOON).orders_last_minute == 0


# --- reading the live market data for the engine ---


class PretendMarket:
    def __init__(self, listing: object, price: object) -> None:
        self._listing, self._price = listing, price

    def list_symbols(self) -> object:
        if isinstance(self._listing, Exception):
            raise self._listing
        return self._listing

    def ticker(self, symbol: str) -> object:
        if isinstance(self._price, Exception):
            raise self._price
        return self._price


def test_the_market_view_carries_rules_and_price() -> None:
    listing = SymbolsView(NOON, False, [rules("ETHUSDT"), rules("BTCUSDT")])
    view = market_view(PretendMarket(listing, ticker()), "BTCUSDT")
    assert view.rules.symbol == "BTCUSDT" and view.rules_stale is False
    assert view.ticker.symbol == "BTCUSDT"


def test_whatever_is_missing_is_refused_by_the_engine(engine: RiskEngine) -> None:
    nothing = market_view(PretendMarket(MarketNotReady(), MarketNotReady()), "BTCUSDT")
    assert (nothing.rules, nothing.rules_stale, nothing.ticker) == (None, True, None)
    assert engine.check(buy("12"), account(), nothing, NOON).code == "unknown_symbol"
    listing = SymbolsView(NOON, False, [rules("BTCUSDT")])
    no_price = market_view(PretendMarket(listing, UnknownSymbol()), "BTCUSDT")
    assert (
        engine.check(buy("12"), account(), no_price, NOON).code == "price_unavailable"
    )
    old = SymbolsView(NOON, True, [rules("BTCUSDT")])
    stale = market_view(PretendMarket(old, ticker()), "BTCUSDT")
    assert engine.check(buy("12"), account(), stale, NOON).code == "rules_stale"


def test_the_limits_cannot_be_swapped_on_a_running_engine(engine: RiskEngine) -> None:
    with pytest.raises(AttributeError):
        engine.limits = LIMITS


# --- a bad reading of the account must never fool the daily pause ---


def test_an_empty_first_reading_does_not_become_the_days_start(
    engine: RiskEngine,
) -> None:
    empty = engine.report(account(cash="0"), NOON)
    assert empty.entries_paused is True and empty.equity == D("0")
    assert "unreadable" in empty.pause_reason
    start_day(engine)  # the real 300 arrives
    decision = engine.check(buy("12"), account(cash="294"), market(), NOON)
    assert decision.code == "daily_loss_pause"  # 2% of 300, not of 0


@pytest.mark.parametrize(
    "broken",
    [
        AccountSnapshot(cash=D("NaN")),
        AccountSnapshot(cash=300.0),
        AccountSnapshot(cash=D("300"), pending_entries={"BTCUSDT": D("-5")}),
        AccountSnapshot(
            cash=D("300"), positions={"BTCUSDT": Position("BTCUSDT", D("NaN"), D("1"))}
        ),
        AccountSnapshot(
            cash=D("300"), positions={"BTCUSDT": Position("BTCUSDT", D("-1"), D("9"))}
        ),
        AccountSnapshot(
            cash=D("300"), positions={"BTCUSDT": Position("BTCUSDT", D("1"), 24.0)}
        ),
        AccountSnapshot(cash=D("1E+30")),
    ],
)
def test_a_broken_account_opens_nothing_and_poisons_nothing(
    engine: RiskEngine, broken: AccountSnapshot
) -> None:
    assert engine.report(broken, NOON).entries_paused is True
    decision = engine.check(buy("12"), broken, market("ETHUSDT"), NOON)
    assert decision.outcome == "rejected"
    assert engine.check(
        buy("12", symbol="ETHUSDT"), broken, market("ETHUSDT"), NOON
    ).code == ("no_equity")
    start_day(engine)  # a good reading afterwards works normally
    assert engine.report(account(), NOON).day_start_equity == D("300")


def test_the_loss_is_watched_even_while_entries_are_blocked_for_another_reason(
    engine: RiskEngine,
) -> None:
    start_day(engine)
    stale = market(ticker=ticker(stale=True))
    assert (
        engine.check(buy("12"), account(cash="292"), stale, NOON).code == "price_stale"
    )
    # The account recovered above the limit, but the 2% was seen: still paused.
    decision = engine.check(buy("12"), account(cash="299"), market(), NOON)
    assert decision.code == "daily_loss_pause"


def test_a_sale_also_lets_the_engine_see_the_days_loss(engine: RiskEngine) -> None:
    start_day(engine)
    losing = account(cash="270", positions={"BTCUSDT": ("0.0004", "23")})  # 293
    assert engine.check(sell("0.0004"), losing, market(), NOON).outcome == "approved"
    decision = engine.check(buy("12"), account(cash="299"), market(), NOON)
    assert decision.code == "daily_loss_pause"
    assert engine.report(account(cash="299"), NOON).entries_paused is True


def test_a_clock_stepping_back_over_midnight_does_not_lift_the_pause(
    engine: RiskEngine,
) -> None:
    day_two = datetime(2026, 1, 2, 0, 0, 2, tzinfo=UTC)
    engine.check(buy("12"), account(), market(), day_two)
    engine.check(buy("12"), account(cash="290"), market(), day_two)  # paused
    back = datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)
    decision = engine.check(buy("12"), account(cash="290"), market(), back)
    assert decision.code == "daily_loss_pause"
    assert engine.report(account(cash="290"), back).day == "2026-01-02"


def test_time_going_backwards_never_frees_a_rate_slot(engine: RiskEngine) -> None:
    for _ in range(8):
        engine.check(buy("12"), account(), market(), NOON)
    earlier = NOON - timedelta(seconds=30)
    assert (
        engine.check(buy("12"), account(), market(), earlier).code == "order_rate_limit"
    )


# --- more exact edges ---


def test_an_order_for_exactly_the_free_cash_passes(engine: RiskEngine) -> None:
    coins = account(cash="12", positions={"ETHUSDT": ("0.1", "288")})
    decision = engine.check(buy("12"), coins, market(), NOON)
    assert decision.outcome == "approved" and decision.notional == D("12")


def test_a_quantity_exactly_at_the_smallest_allowed_passes(engine: RiskEngine) -> None:
    view = market(rules=rules(min_quantity=D("0.0002")))
    assert engine.check(buy("12"), account(), view, NOON).outcome == "approved"
    view = market(rules=rules(min_quantity=D("0.00021")))
    assert engine.check(buy("12"), account(), view, NOON).code == "below_minimum"


def test_a_sale_exactly_at_the_exchange_minimum_passes(engine: RiskEngine) -> None:
    small = account(cash="295", positions={"BTCUSDT": ("0.0001", "5")})
    decision = engine.check(sell("0.0001", price="50000.00"), small, market(), NOON)
    assert decision.outcome == "approved" and decision.notional == D("5")
    under = engine.check(sell("0.0001", price="49999.99"), small, market(), NOON)
    assert under.code == "below_minimum"


def test_a_sale_uses_a_rate_slot_but_is_never_refused_by_the_rate(
    engine: RiskEngine,
) -> None:
    for _ in range(12):
        assert (
            engine.check(sell("0.0004"), held(), market(), NOON).outcome == "approved"
        )
    assert engine.report(account(), NOON).orders_last_minute == 12
    assert engine.check(buy("12"), account(), market(), NOON).code == "order_rate_limit"


def test_a_price_for_another_pair_is_refused(engine: RiskEngine) -> None:
    view = market(ticker=ticker("ETHUSDT"))
    assert engine.check(buy("12"), account(), view, NOON).code == "price_unavailable"


def test_what_is_promised_to_another_exit_order_cannot_be_sold_twice(
    engine: RiskEngine,
) -> None:
    half = AccountSnapshot(
        cash=D("276"),
        positions={"BTCUSDT": Position("BTCUSDT", D("0.0004"), D("24"), D("0.0003"))},
    )
    decision = engine.check(sell("0.0004", price="60000.00"), half, market(), NOON)
    assert decision.outcome == "reduced" and decision.quantity == D("0.0001")
    all_promised = AccountSnapshot(
        cash=D("276"),
        positions={"BTCUSDT": Position("BTCUSDT", D("0.0004"), D("24"), D("0.0004"))},
    )
    assert engine.check(sell("0.0004"), all_promised, market(), NOON).code == (
        "nothing_to_sell"
    )


def test_numbers_too_large_to_calculate_with_are_refused_not_crashed(
    engine: RiskEngine,
) -> None:
    huge = OrderRequest("BTCUSDT", Side.BUY, D("1E+25"), D("60000"))
    assert engine.check(huge, account(), market(), NOON).code == "invalid_order"
    odd = OrderRequest("BTCUSDT", Side.SELL, D("999999999999"), D("999999999999"))
    view = market(rules=rules(tick_size=D("1E-27"), step_size=D("1E-27")))
    assert engine.check(odd, held(), view, NOON).outcome == "rejected"


def test_the_engine_refuses_limits_it_cannot_enforce() -> None:
    two_per_pair = LIMITS.model_copy(update={"max_positions_per_symbol": 2})
    with pytest.raises(ValueError, match="one position per pair"):
        RiskEngine(two_per_pair)


# --- surviving a restart ---


def test_the_engine_gives_back_what_it_must_remember() -> None:
    engine = RiskEngine(LIMITS)
    assert engine.state() == RiskState(None, D(0), False, "")
    state = RiskState(date(2026, 1, 1), D("300"), True, "kill switch")
    engine.restore(state)
    assert engine.state() == state
    fresh = RiskEngine(LIMITS)
    fresh.restore(engine.state())
    assert fresh.state() == state


@pytest.mark.parametrize("equity", ["0", "-5", "NaN", "Infinity", "10000000000000"])
def test_a_stored_day_without_a_usable_start_is_refused(equity: str) -> None:
    engine = RiskEngine(LIMITS)
    with pytest.raises(ValueError, match="no usable starting equity"):
        engine.restore(RiskState(date(2026, 1, 1), D(equity), True, ""))
    assert engine.state().day is None  # nothing was taken over


def test_a_stored_state_without_a_day_restores_only_the_outside_pause() -> None:
    engine = RiskEngine(LIMITS)
    engine.restore(RiskState(None, D("NaN"), True, "  stopped  "))
    assert engine.state() == RiskState(None, D(0), False, "stopped")
