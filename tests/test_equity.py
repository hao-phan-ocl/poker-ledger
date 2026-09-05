"""Equity checked against exact enumeration and the published preflop tables."""

from itertools import combinations

import numpy as np
import pytest

from app.poker import equity as equity_mod
from app.poker.cards import NUM_CARDS, parse_cards
from app.poker.equity import EquityError, equity, find_draws, pot_odds
from app.poker.evaluator import evaluate


def cards(text: str) -> list[int]:
    return parse_cards(text.split()) if text else []


def _exact_river_equity(hole, board):
    known = set(hole + board)
    deck = [c for c in range(NUM_CARDS) if c not in known]
    hero = int(evaluate(np.array([hole + board], dtype=np.int64))[0])
    opponents = np.array(
        [[a, b, *board] for a, b in combinations(deck, 2)], dtype=np.int64
    )
    scores = evaluate(opponents)
    total = len(scores)
    return (
        int((hero > scores).sum()) / total,
        int((hero == scores).sum()) / total,
        int((hero < scores).sum()) / total,
    )


@pytest.mark.parametrize(
    "hole,board",
    [
        ("Ah Kd", "Qc Js Th 2d 3c"),  # broadway straight
        ("7h 2d", "Ks Qd 9c 4s 3h"),  # nothing
        ("As Ks", "Qs Js 2s 7d 8c"),  # made flush
        ("9h 9d", "9s 4c 4d Kh 2c"),  # full house
    ],
)
def test_monte_carlo_matches_exact_enumeration(hole, board):
    hero, table = cards(hole), cards(board)
    exact_win, exact_tie, exact_lose = _exact_river_equity(hero, table)
    result = equity(hero, table, opponents=1, trials=120_000, seed=42)
    assert result.win == pytest.approx(exact_win, abs=0.01)
    assert result.tie == pytest.approx(exact_tie, abs=0.01)
    assert result.lose == pytest.approx(exact_lose, abs=0.01)


@pytest.mark.parametrize(
    "hole,expected",
    [
        ("Ah Ad", 0.852),  # the best starting hand
        ("Kh Kd", 0.824),
        ("Ah Kh", 0.670),  # suited
        ("Ah Kd", 0.654),  # offsuit
        ("2h 2d", 0.503),
        ("7h 2d", 0.346),  # famously the worst
    ],
)
def test_preflop_equity_matches_published_figures(hole, expected):
    result = equity(cards(hole), [], opponents=1, trials=200_000, seed=5)
    assert result.equity == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    "opponents,expected",
    [(1, 0.852), (2, 0.734), (3, 0.639), (4, 0.559), (5, 0.493), (6, 0.436), (8, 0.346)],
)
def test_multiway_equity_matches_published_figures(opponents, expected):
    """Guards the deal. A biased shuffle is invisible heads-up and worth ten
    points at eight opponents, so only a multiway check against known values
    catches it."""
    result = equity(cards("Ah Ad"), [], opponents=opponents, trials=200_000, seed=11)
    assert result.equity == pytest.approx(expected, abs=0.01)


def test_every_seat_is_dealt_from_the_same_deck():
    """Every slot must see every rank equally often."""
    from app.poker.equity import _CHUNK

    rng = np.random.default_rng(0)
    deck = np.arange(52, dtype=np.int64)
    trials = 40_000
    per_trial = 9
    drawn = rng.permuted(np.tile(deck, (trials, 1)), axis=1)[:, :per_trial]

    for slot in range(per_trial):
        mean_rank = (drawn[:, slot] >> 2).mean()
        # Ranks run 0-12, so a fair deal averages 6.0 in every slot.
        assert mean_rank == pytest.approx(6.0, abs=0.15), f"slot {slot} is skewed"
    assert _CHUNK > 0


def test_probabilities_sum_to_one():
    result = equity(cards("Ah Kh"), cards("Qc Js 2d"), opponents=3, trials=20_000, seed=1)
    assert result.win + result.tie + result.lose == pytest.approx(1.0)


def test_equity_falls_as_opponents_are_added():
    results = [
        equity(cards("Ah Ad"), [], opponents=n, trials=40_000, seed=3).equity
        for n in (1, 3, 6)
    ]
    assert results == sorted(results, reverse=True)


def test_unbeatable_hand_always_wins():
    result = equity(
        cards("As Ks"), cards("Qs Js Ts 2d 3c"), opponents=2, trials=5_000, seed=9
    )
    assert result.win == 1.0
    assert result.lose == 0.0
    assert result.made_hand == "straight flush"


def test_same_seed_gives_same_answer():
    a = equity(cards("Ah Kh"), [], 2, trials=10_000, seed=99)
    b = equity(cards("Ah Kh"), [], 2, trials=10_000, seed=99)
    assert (a.win, a.tie, a.equity) == (b.win, b.tie, b.equity)


def test_more_trials_shrink_the_error_bar():
    small = equity(cards("Ah Kh"), [], 1, trials=5_000, seed=2)
    large = equity(cards("Ah Kh"), [], 1, trials=200_000, seed=2)
    assert large.margin_of_error < small.margin_of_error


def test_street_and_made_hand_are_reported():
    assert equity(cards("Ah Ad"), [], 1, trials=1_000).street == "preflop"
    flop = equity(cards("Ah Ad"), cards("Ac 7d 2s"), 1, trials=1_000)
    assert flop.street == "flop"
    assert flop.made_hand == "three of a kind"


class TestDraws:
    def test_flush_and_straight_draws_are_counted(self):
        draws = {
            d.description: d.outs for d in find_draws(cards("As Ks"), cards("Qs Js 2h"))
        }
        # Nine spades remain: one makes a straight flush, eight a plain flush.
        assert draws["straight flush"] == 1
        assert draws["flush"] == 8
        # Three tens are left after the Ts was counted above.
        assert draws["straight"] == 3

    def test_open_ended_straight_draw_has_eight_outs(self):
        draws = {
            d.description: d.outs for d in find_draws(cards("9h 8h"), cards("7s 6d 2c"))
        }
        assert draws["straight"] == 8

    def test_gutshot_has_four_outs(self):
        draws = {
            d.description: d.outs for d in find_draws(cards("Ah Kd"), cards("Qc Js 2h"))
        }
        assert draws["straight"] == 4

    def test_overcards_count_but_board_pairs_do_not(self):
        """Pairing the board gives every opponent the same hand."""
        draws = {
            d.description: d.outs for d in find_draws(cards("Ah Kd"), cards("Qc Js 2h"))
        }
        assert draws["one pair"] == 6

    def test_pairing_the_board_is_not_two_pair_worth_having(self):
        """Aces on K-Q-2: a king lifts you to "two pair" on paper, but every
        opponent gets those kings too, so nothing has moved."""
        draws = {
            d.description: d.outs for d in find_draws(cards("Ah Ad"), cards("Ks Qd 2c"))
        }
        assert "two pair" not in draws
        assert draws["three of a kind"] == 2

    def test_two_pair_counts_when_it_uses_a_hole_card(self):
        """A-K with a king on board: only the three aces are real outs."""
        draws = {
            d.description: d.outs for d in find_draws(cards("Ah Kd"), cards("Ks Qd 2c"))
        }
        assert draws["two pair"] == 3
        assert draws["three of a kind"] == 2

    def test_a_flush_that_lands_on_the_board_is_not_yours(self):
        """Four spades out there and none in your hand - the fifth is
        everyone's flush, not your out."""
        draws = {
            d.description: d.outs
            for d in find_draws(cards("Ah Kd"), cards("Qs Js 2s 7s"))
        }
        assert "flush" not in draws

    def test_a_straight_sitting_on_the_board_is_not_yours(self):
        draws = {
            d.description: d.outs
            for d in find_draws(cards("Ah Kd"), cards("5s 6d 7c 8h"))
        }
        assert "straight" not in draws

    def test_a_straight_using_your_cards_still_counts(self):
        draws = {
            d.description: d.outs for d in find_draws(cards("9h 8h"), cards("7s 6d 2c"))
        }
        assert draws["straight"] == 8

    def test_no_draws_preflop_or_on_the_river(self):
        assert find_draws(cards("Ah Kd"), []) == []
        assert find_draws(cards("Ah Kd"), cards("Qc Js 2h 3d 4c")) == []


class TestPriceLadder:
    def test_required_equity_per_bet_size(self):
        """Calling B into a pot of P puts B in to win P + 2B, so the
        break-even point is B / (P + 2B). Their bet is already part of what
        you stand to win, which makes these kinder than they first look."""
        required = {row.bet: row.required_equity for row in equity_mod.price_ladder(0.5)}
        assert required["a third of the pot"] == pytest.approx(0.200, abs=0.001)
        assert required["half the pot"] == pytest.approx(0.250, abs=0.001)
        assert required["two-thirds of the pot"] == pytest.approx(0.286, abs=0.001)
        assert required["the whole pot"] == pytest.approx(0.333, abs=0.001)
        assert required["twice the pot"] == pytest.approx(0.400, abs=0.001)

    def test_bigger_bets_demand_more(self):
        rows = equity_mod.price_ladder(0.5)
        needed = [row.required_equity for row in rows]
        assert needed == sorted(needed)

    @pytest.mark.parametrize(
        "hand_equity,expected",
        [
            (0.05, "Too weak to call even a small bet."),
            (0.22, "Worth calling up to a third of the pot."),
            (0.27, "Worth calling up to half the pot."),
            (0.30, "Worth calling up to two-thirds of the pot."),
            (0.35, "Worth calling up to the whole pot."),
            (0.90, "Worth calling any bet at all."),
        ],
    )
    def test_the_headline_names_the_biggest_affordable_bet(self, hand_equity, expected):
        assert equity_mod.biggest_call(hand_equity) == expected

    def test_prices_come_back_on_every_result(self):
        result = equity(cards("Ah Kh"), [], 1, trials=2_000, seed=4)
        assert len(result.prices) == 5
        assert result.biggest_call


class TestPotOdds:
    def test_required_equity_is_the_price_of_the_call(self):
        # Calling 25 into a pot of 100 needs 25/125 = 20%.
        odds = pot_odds(10_000, 2_500, actual_equity=0.35)
        assert odds.required_equity == pytest.approx(0.20)
        assert odds.profitable

    def test_a_bad_price_is_reported_as_such(self):
        odds = pot_odds(10_000, 10_000, actual_equity=0.35)
        assert odds.required_equity == pytest.approx(0.50)
        assert not odds.profitable
        assert "loses money" in odds.verdict

    def test_rejects_nonsense_amounts(self):
        with pytest.raises(EquityError):
            pot_odds(1_000, 0, 0.5)
        with pytest.raises(EquityError):
            pot_odds(-1, 100, 0.5)


class TestValidation:
    def test_rejects_wrong_number_of_hole_cards(self):
        with pytest.raises(EquityError, match="2 hole cards"):
            equity(cards("Ah Kd Qc"), [], 1, trials=100)

    def test_rejects_impossible_board_size(self):
        with pytest.raises(EquityError, match="0, 3, 4 or 5"):
            equity(cards("Ah Kd"), cards("Qc Js"), 1, trials=100)

    def test_rejects_a_card_used_twice(self):
        with pytest.raises(EquityError, match="twice"):
            equity(cards("Ah Kd"), cards("Ah Js 2c"), 1, trials=100)

    def test_rejects_impossible_opponent_counts(self):
        with pytest.raises(EquityError):
            equity(cards("Ah Kd"), [], 0, trials=100)
        with pytest.raises(EquityError):
            equity(cards("Ah Kd"), [], 10, trials=100)


class TestChanceOfHitting:
    def test_nine_outs_is_two_draws_not_nine(self):
        """Outs count cards in the deck, not cards you receive. Nine outs on
        the flop is nine chances across two draws."""
        from app.poker.equity import chance_of_hitting

        assert chance_of_hitting(9, 47, 2) == pytest.approx(0.350, abs=0.001)
        assert chance_of_hitting(9, 46, 1) == pytest.approx(0.196, abs=0.001)

    def test_it_tracks_the_rule_of_four_and_two(self):
        """The shortcut players use at the table: outs x 4 on the flop, x 2 on
        the turn. It drifts by up to two points, and further above ten outs -
        15 outs is really 54%, not the 60% the rule claims."""
        from app.poker.equity import chance_of_hitting

        for outs in (4, 8, 9):
            assert chance_of_hitting(outs, 47, 2) * 100 == pytest.approx(outs * 4, abs=2)
            assert chance_of_hitting(outs, 46, 1) * 100 == pytest.approx(outs * 2, abs=2)

        assert chance_of_hitting(15, 47, 2) * 100 == pytest.approx(54.1, abs=0.5)

    def test_one_card_to_come_is_worth_about_half(self):
        from app.poker.equity import chance_of_hitting

        assert chance_of_hitting(9, 46, 1) < chance_of_hitting(9, 47, 2)

    def test_draws_carry_their_chance(self):
        flop = {d.description: d for d in find_draws(cards("As Ks"), cards("Qs Js 2h"))}
        turn = {
            d.description: d for d in find_draws(cards("As Ks"), cards("Qs Js 2h 3d"))
        }
        assert flop["flush"].outs == turn["flush"].outs == 8
        assert flop["flush"].cards_to_come == 2
        assert turn["flush"].cards_to_come == 1
        # Same outs, one fewer draw, so roughly half the chance.
        assert turn["flush"].chance < flop["flush"].chance


class TestOutcomes:
    def test_every_ending_is_accounted_for(self):
        result = equity(cards("As Ks"), cards("Qs Js 2h"), 2, trials=50_000, seed=6)
        assert sum(o.chance for o in result.outcomes) == pytest.approx(1.0, abs=0.001)

    def test_it_is_conditional_on_the_board(self):
        """Four to a flush already showing makes a flush far more likely than
        the same two cards with nothing out there."""
        drawing = equity(cards("As Ks"), cards("Qs Js 2h"), 1, trials=50_000, seed=7)
        blank = equity(cards("As Ks"), cards("Qd Jc 2h"), 1, trials=50_000, seed=7)
        flush = next((o.chance for o in drawing.outcomes if o.hand == "flush"), 0)
        no_flush = next((o.chance for o in blank.outcomes if o.hand == "flush"), 0)
        assert flush > 0.25
        assert no_flush < 0.02

    def test_better_hands_win_more_often_when_made(self):
        result = equity(cards("As Ks"), cards("Qs Js 2h"), 2, trials=50_000, seed=8)
        by_hand = {o.hand: o.wins_when_made for o in result.outcomes}
        assert by_hand["flush"] > by_hand["one pair"] > by_hand["high card"]

    def test_the_distribution_agrees_with_the_outs(self):
        """Nine spades left: the flush and straight-flush endings should add
        up to roughly the chance of hitting nine outs in two cards."""
        result = equity(cards("As Ks"), cards("Qs Js 2h"), 1, trials=200_000, seed=9)
        spades = sum(
            o.chance for o in result.outcomes if o.hand in ("flush", "straight flush")
        )
        assert spades == pytest.approx(0.35, abs=0.02)
