"""Slow, obvious hand evaluator, used only as the test oracle for evaluator.py.

Scores a hand as a tuple (category, *tiebreakers), which compares correctly
under Python's tuple ordering with no bit-packing.
"""

from itertools import combinations

from .cards import rank_of, suit_of

HIGH_CARD = 0
ONE_PAIR = 1
TWO_PAIR = 2
TRIPS = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
QUADS = 7
STRAIGHT_FLUSH = 8

CATEGORY_NAMES = {
    HIGH_CARD: "high card",
    ONE_PAIR: "one pair",
    TWO_PAIR: "two pair",
    TRIPS: "three of a kind",
    STRAIGHT: "straight",
    FLUSH: "flush",
    FULL_HOUSE: "full house",
    QUADS: "four of a kind",
    STRAIGHT_FLUSH: "straight flush",
}


def _straight_high(ranks: set[int]) -> int | None:
    """Highest card of a straight within ``ranks``, or None.

    In the wheel (A-2-3-4-5) the ace plays low, so the high card is the five.
    """
    for high in range(12, 2, -1):
        if all(high - offset in ranks for offset in range(5)):
            return high
    if {12, 0, 1, 2, 3} <= ranks:
        return 3
    return None


def eval5(cards) -> tuple:
    ranks = [rank_of(c) for c in cards]
    suits = [suit_of(c) for c in cards]

    counts: dict[int, int] = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1

    # Ranks ordered by how many of them we hold, then by rank.  That is
    # exactly the order poker uses to break ties: the trips in a full house
    # matter before the pair, the pair before its kicker.
    grouped = sorted(counts, key=lambda r: (-counts[r], -r))
    shape = sorted(counts.values(), reverse=True)

    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(set(ranks))

    if is_flush and straight_high is not None:
        return (STRAIGHT_FLUSH, straight_high)
    if shape == [4, 1]:
        return (QUADS, *grouped)
    if shape == [3, 2]:
        return (FULL_HOUSE, *grouped)
    if is_flush:
        return (FLUSH, *sorted(ranks, reverse=True))
    if straight_high is not None:
        return (STRAIGHT, straight_high)
    if shape == [3, 1, 1]:
        return (TRIPS, *grouped)
    if shape == [2, 2, 1]:
        return (TWO_PAIR, *grouped)
    if shape == [2, 1, 1, 1]:
        return (ONE_PAIR, *grouped)
    return (HIGH_CARD, *sorted(ranks, reverse=True))


def eval7(cards) -> tuple:
    """Best five-card score from five, six or seven cards."""
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(combo) for combo in combinations(cards, 5))
