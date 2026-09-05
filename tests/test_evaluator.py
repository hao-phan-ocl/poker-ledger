"""Fuzzes evaluator.py against reference.py. Where they disagree, reference wins."""

import random

import numpy as np
import pytest

from app.poker import reference
from app.poker.cards import parse_cards
from app.poker.evaluator import category_of, evaluate


def _score_one(cards) -> int:
    return int(evaluate(np.array([cards], dtype=np.int64))[0])


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


@pytest.mark.parametrize("width", [5, 6, 7])
def test_categories_match_reference(width):
    rng = random.Random(20260905 + width)
    deck = list(range(52))
    for _ in range(4000):
        hand = rng.sample(deck, width)
        assert category_of(_score_one(hand)) == reference.eval7(hand)[0]


@pytest.mark.parametrize("width", [5, 7])
def test_ordering_matches_reference(width):
    """Categories agreeing is not enough - kickers must break ties identically."""
    rng = random.Random(777 + width)
    deck = list(range(52))
    for _ in range(6000):
        a = rng.sample(deck, width)
        b = rng.sample(deck, width)
        fast = _sign(_score_one(a) - _score_one(b))
        ref_a, ref_b = reference.eval7(a), reference.eval7(b)
        slow = (ref_a > ref_b) - (ref_a < ref_b)
        assert fast == slow, f"{a} vs {b}: fast said {fast}, reference said {slow}"


def test_ordering_on_shared_boards():
    """Shared boards collide on kickers far more often than random hands."""
    rng = random.Random(31337)
    deck = list(range(52))
    for _ in range(4000):
        drawn = rng.sample(deck, 9)
        board, hole_a, hole_b = drawn[:5], drawn[5:7], drawn[7:9]
        a, b = hole_a + board, hole_b + board
        fast = _sign(_score_one(a) - _score_one(b))
        ref_a, ref_b = reference.eval7(a), reference.eval7(b)
        slow = (ref_a > ref_b) - (ref_a < ref_b)
        assert fast == slow, f"board {board}: {hole_a} vs {hole_b}"


def _score_str(cards: str) -> int:
    return _score_one(parse_cards(cards.split()))


def test_known_hands_rank_in_order():
    ordered = [
        "As Ks Qs Js Ts",  # royal flush
        "9s 8s 7s 6s 5s",  # straight flush
        "5s 4s 3s 2s As",  # steel wheel - the ace plays low
        "Ah Ad Ac As Kh",  # quads
        "Ah Ad Ac Kh Kd",  # full house
        "Ah Kh Qh Jh 9h",  # flush
        "Ah Kd Qc Js Th",  # broadway straight
        "5h 4d 3c 2s Ah",  # wheel
        "Ah Ad Ac Kh Qd",  # trips
        "Ah Ad Kh Kd Qc",  # two pair
        "Ah Ad Kh Qd Jc",  # one pair
        "Ah Kd Qc Js 9h",  # high card
    ]
    scores = [_score_str(hand) for hand in ordered]
    assert scores == sorted(scores, reverse=True), "hand categories are out of order"


def test_wheel_is_the_weakest_straight():
    assert _score_str("5h 4d 3c 2s Ah") < _score_str("6h 5d 4c 3s 2h")


def test_kickers_break_ties():
    assert _score_str("Ah Ad Kh Qd Jc") > _score_str("Ah Ad Kh Qd Tc")
    assert _score_str("Ah Ad Kh Qd Jc") == _score_str("As Ac Ks Qs Js")


def test_seven_card_kicker_edge_cases():
    """A lower-count rank can still win the kicker slot."""
    # Three pairs: the spare queen plays, not the third pair.
    assert _score_str("Ah Ad Kh Kd 2c 2s Qh") == _score_str("Ah Ad Kh Kd 3c 3s Qd")
    assert _score_str("Ah Ad Kh Kd 2c 2s Qh") > _score_str("Ah Ad Kh Kd 2c 2s Jh")
    # Quads plus a pair: the higher spare card is the kicker, not the pair.
    assert _score_str("Ah Ad Ac As 2c 2s Kh") > _score_str("Ah Ad Ac As 3c 3s Qh")


def test_best_five_of_seven_is_chosen():
    assert _score_str("As Ks Qs Js Ts 2c 3d") == _score_str("As Ks Qs Js Ts")


def test_batch_matches_individual_scoring():
    rng = random.Random(11)
    hands = np.array([rng.sample(range(52), 7) for _ in range(500)], dtype=np.int64)
    batch = evaluate(hands)
    for row, score in zip(hands, batch, strict=True):
        assert _score_one(list(row)) == score


def test_rejects_bad_shapes():
    with pytest.raises(ValueError):
        evaluate(np.arange(7, dtype=np.int64))
    with pytest.raises(ValueError):
        evaluate(np.zeros((3, 4), dtype=np.int64))
