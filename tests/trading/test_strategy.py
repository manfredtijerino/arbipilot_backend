"""The dip rule gives the same answer as the textbook formula, exactly."""

import random
from fractions import Fraction

from trading.strategy import WINDOW, Dip, find_dips


def textbook(closes: list[int], index: int, k: int) -> bool:
    """close <= average - k * standard deviation, over the last 60 closes."""
    window = closes[index - WINDOW + 1 : index + 1]
    if len(window) < WINDOW or any(c <= 0 for c in window):
        return False
    mean = Fraction(sum(window), WINDOW)
    variance = sum((Fraction(c) - mean) ** 2 for c in window) / WINDOW
    below = mean - closes[index]
    return below > 0 and below * below >= k * k * variance


def random_walk(seed: int, length: int, start: int = 6_000_000) -> list[int]:
    rng = random.Random(seed)
    prices, price = [], start
    for _ in range(length):
        price = max(1, price + rng.randint(-3000, 3000))
        prices.append(price)
    return prices


def test_it_agrees_with_the_textbook_on_random_prices() -> None:
    for seed in range(5):
        closes = random_walk(seed, 1500)
        for k in (2, 3, 4):
            found = {dip.index for dip in find_dips(closes, 2) if dip.at_least(k)}
            expected = {i for i in range(len(closes)) if textbook(closes, i, k)}
            assert found == expected and (k > 2 or found)


def test_the_distance_is_the_share_under_the_average() -> None:
    closes = [10_000] * 59 + [9_900]
    (dip,) = find_dips(closes, 2)
    assert dip.index == 59 and dip.close == 9_900
    mean = Fraction(sum(closes), 60)
    assert dip.distance == (mean - 9_900) / mean == Fraction(59, 5999)
    assert dip.at_least(4) and dip.at_least(7) and not dip.at_least(8)


def test_exactly_k_standard_deviations_counts() -> None:
    # below^2 == k^2 * spread is the exact edge: 36 == 2*2*9.
    exact = Dip(0, 10, below=6, spread=9, total=60)
    assert exact.at_least(2) and not exact.at_least(3)
    closes = [100] * 60
    closes[0], closes[-1] = 104, 96  # average 100, the last close 4 under it
    (dip,) = list(find_dips(closes, 1))
    assert dip.below == 240 and dip.spread == 60 * 32
    assert dip.at_least(5) and not dip.at_least(6)  # 57600 against 1920 * k^2


def test_no_dip_before_sixty_closes_or_across_a_gap() -> None:
    assert list(find_dips([10_000] * 58 + [9_000], 2)) == []
    with_gap = [10_000] * 40 + [0] + [10_000] * 58 + [9_000]
    assert list(find_dips(with_gap, 2)) == []  # only 59 since the gap
    healed = [10_000] * 40 + [0] + [10_000] * 59 + [9_000]
    assert [dip.index for dip in find_dips(healed, 2)] == [100]


def test_a_flat_or_rising_price_is_never_a_dip() -> None:
    assert list(find_dips([10_000] * 200, 2)) == []
    assert list(find_dips(list(range(10_000, 10_200)), 2)) == []


def test_an_answer_never_depends_on_later_prices() -> None:
    closes = random_walk(7, 900)
    changed = closes[:600] + [c * 3 for c in closes[600:]]
    before = [d for d in find_dips(closes, 2) if d.index < 600]
    after = [d for d in find_dips(changed, 2) if d.index < 600]
    assert before == after and before
