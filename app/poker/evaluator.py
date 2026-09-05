"""Vectorised hand evaluator. Correctness is asserted by tests/test_evaluator.py,
which fuzzes it against reference.py - not by reading this.

Score layout, so integer comparison ranks any two hands:

    bits 21-24  category      (0 high card ... 8 straight flush)
    bits 17-20  primary rank  (quad / trips / top pair / straight high)
    bits 13-16  secondary     (pair in a full house, second pair)
    bits 0-12   kicker mask   (one bit per rank, high bit = high rank)

The kicker mask compares correctly because a higher bit outweighs every lower
bit combined. It is trimmed to the kickers the category actually uses, so a
hand cannot win a tie on cards outside its best five.
"""

import numpy as np

_RANK_POWERS = (1 << np.arange(13)).astype(np.int64)

_BIT_INDEX = np.zeros(1 << 13, dtype=np.int64)
for _i in range(13):
    _BIT_INDEX[1 << _i] = _i

# Ascending by high card, so later assignments overwrite lower straights. The
# wheel is first: the ace plays low, making the five its high card.
_STRAIGHTS: list[tuple[int, int]] = [
    (3, (1 << 12) | (1 << 3) | (1 << 2) | (1 << 1) | 1),
]
_STRAIGHTS += [(high, 0b11111 << (high - 4)) for high in range(4, 13)]

CAT_SHIFT = 21
P1_SHIFT = 17
P2_SHIFT = 13


def _highest_bit(x: np.ndarray) -> np.ndarray:
    """Isolate the highest set bit of each value (0 stays 0)."""
    y = x | (x >> 1)
    y |= y >> 2
    y |= y >> 4
    y |= y >> 8
    return y - (y >> 1)


def _top_rank(bits: np.ndarray) -> np.ndarray:
    """Index of the highest set bit. Meaningless for 0, never used there."""
    return _BIT_INDEX[_highest_bit(bits)]


def _keep_top(bits: np.ndarray, k: int) -> np.ndarray:
    """Keep only the k highest set bits, dropping cards that do not play."""
    kept = np.zeros_like(bits)
    rest = bits.copy()
    for _ in range(k):
        hb = _highest_bit(rest)
        kept |= hb
        rest &= ~hb
    return kept


def _straight_high(bits: np.ndarray) -> np.ndarray:
    """High card of the best straight in each rank mask, or -1 for none."""
    out = np.full(bits.shape, -1, dtype=np.int64)
    for high, pattern in _STRAIGHTS:
        out = np.where((bits & pattern) == pattern, high, out)
    return out


def evaluate(hands: np.ndarray) -> np.ndarray:
    """Score an ``(n, cards)`` array of card ints; higher is better.

    Works for any hand width from 5 to 7 cards. Scores are comparable only
    against each other, never as an absolute strength.
    """
    hands = np.asarray(hands, dtype=np.int64)
    if hands.ndim != 2:
        raise ValueError(f"expected a 2-d (n, cards) array, got shape {hands.shape}")
    n, width = hands.shape
    if not 5 <= width <= 7:
        raise ValueError(f"expected 5 to 7 cards per hand, got {width}")

    ranks = hands >> 2
    suits = hands & 3

    rows = np.repeat(np.arange(n, dtype=np.int64), width)
    rank_counts = np.bincount(rows * 13 + ranks.ravel(), minlength=n * 13).reshape(n, 13)
    suit_counts = np.bincount(rows * 4 + suits.ravel(), minlength=n * 4).reshape(n, 4)

    rank_bit = (1 << ranks).astype(np.int64)
    rank_bits = np.bitwise_or.reduce(rank_bit, axis=1)

    quad_bits = ((rank_counts == 4) * _RANK_POWERS).sum(axis=1)
    trip_bits = ((rank_counts == 3) * _RANK_POWERS).sum(axis=1)
    pair_bits = ((rank_counts == 2) * _RANK_POWERS).sum(axis=1)

    n4 = (rank_counts == 4).sum(axis=1)
    n3 = (rank_counts == 3).sum(axis=1)
    n2 = (rank_counts == 2).sum(axis=1)

    # With seven cards at most one suit can reach five, so argmax is
    # unambiguous wherever a flush actually exists.
    has_flush = suit_counts.max(axis=1) >= 5
    flush_suit = suit_counts.argmax(axis=1)
    in_flush = suits == flush_suit[:, None]
    flush_bits = np.where(
        has_flush, np.bitwise_or.reduce(np.where(in_flush, rank_bit, 0), axis=1), 0
    )

    straight_high = _straight_high(rank_bits)
    sf_high = _straight_high(flush_bits)

    quad_rank = _top_rank(quad_bits)
    quad_kicker = _keep_top(rank_bits & ~quad_bits, 1)

    top_trip_bit = _highest_bit(trip_bits)
    trip_rank = _BIT_INDEX[top_trip_bit]
    # A second trip can serve as the pair of a full house. Seven cards cannot
    # hold two trips and a separate pair, so the higher of what remains wins.
    fh_pair_rank = _top_rank((trip_bits & ~top_trip_bit) | pair_bits)
    trips_kickers = _keep_top(rank_bits & ~trip_bits, 2)

    top_pair_bit = _highest_bit(pair_bits)
    second_pair_bit = _highest_bit(pair_bits & ~top_pair_bit)
    top_pair_rank = _BIT_INDEX[top_pair_bit]
    second_pair_rank = _BIT_INDEX[second_pair_bit]
    # Three pairs in seven cards leaves a spare card that may outrank the
    # third pair, so the kicker comes from everything the two pairs leave.
    two_pair_kicker = _keep_top(rank_bits & ~top_pair_bit & ~second_pair_bit, 1)
    one_pair_kickers = _keep_top(rank_bits & ~pair_bits, 3)

    zero = np.zeros(n, dtype=np.int64)

    def score(cat, p1=zero, p2=zero, kickers=zero):
        return (cat << CAT_SHIFT) | (p1 << P1_SHIFT) | (p2 << P2_SHIFT) | kickers

    conditions = [
        sf_high >= 0,
        n4 >= 1,
        (n3 >= 1) & ((n3 >= 2) | (n2 >= 1)),
        has_flush,
        straight_high >= 0,
        n3 >= 1,
        n2 >= 2,
        n2 == 1,
    ]
    choices = [
        score(8, sf_high),
        score(7, quad_rank, kickers=quad_kicker),
        score(6, trip_rank, fh_pair_rank),
        score(5, kickers=_keep_top(flush_bits, 5)),
        score(4, straight_high),
        score(3, trip_rank, kickers=trips_kickers),
        score(2, top_pair_rank, second_pair_rank, two_pair_kicker),
        score(1, top_pair_rank, kickers=one_pair_kickers),
    ]
    return np.select(
        conditions, choices, default=score(0, kickers=_keep_top(rank_bits, 5))
    )


def category_of(score: int) -> int:
    return int(score) >> CAT_SHIFT
