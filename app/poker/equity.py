"""Monte Carlo equity, draws and pot odds for Texas Hold'em.

Opponents are assumed to hold any two cards, so results are a ceiling against
anyone who only plays good hands.
"""

from dataclasses import dataclass, field
from math import sqrt

import numpy as np

from .cards import NUM_CARDS, card_str
from .evaluator import evaluate
from .reference import CATEGORY_NAMES, ONE_PAIR

_CHUNK = 20_000  # keeps memory flat however many trials are asked for

MAX_OPPONENTS = 9
VALID_BOARD_SIZES = (0, 3, 4, 5)
STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


class EquityError(ValueError):
    """Raised when a hand or board cannot be evaluated as described."""


@dataclass
class Draw:
    description: str
    outs: int
    cards: list[str]


@dataclass
class PriceRow:
    bet: str
    required_equity: float
    worth_calling: bool


@dataclass
class EquityResult:
    win: float
    tie: float
    lose: float
    equity: float
    margin_of_error: float
    trials: int
    street: str
    made_hand: str
    draws: list[Draw] = field(default_factory=list)
    prices: list[PriceRow] = field(default_factory=list)
    biggest_call: str = ""


# Bet sizes as a fraction of the pot before the bet, which is how players
# describe them: "he bet half the pot".
BET_SIZES: list[tuple[str, float]] = [
    ("a third of the pot", 1 / 3),
    ("half the pot", 1 / 2),
    ("two-thirds of the pot", 2 / 3),
    ("the whole pot", 1.0),
    ("twice the pot", 2.0),
]


def price_ladder(equity: float) -> list[PriceRow]:
    """What each common bet size demands, and whether this hand can pay it.

    Calling a bet of B into a pot of P means putting B in to win P + 2B, so
    the break-even point is B / (P + 2B). Their bet is already in the pot you
    are being offered, which is why the numbers are kinder than they look.
    """
    rows = []
    for label, fraction in BET_SIZES:
        required = fraction / (1 + 2 * fraction)
        rows.append(
            PriceRow(
                bet=label,
                required_equity=required,
                worth_calling=equity >= required,
            )
        )
    return rows


def biggest_call(equity: float) -> str:
    """The largest of the listed bets this hand can profitably call."""
    affordable = [row.bet for row in price_ladder(equity) if row.worth_calling]
    if not affordable:
        return "Too weak to call even a small bet."
    if len(affordable) == len(BET_SIZES):
        return "Worth calling any bet at all."
    return f"Worth calling up to {affordable[-1]}."


def _validate(hole: list[int], board: list[int], opponents: int) -> None:
    if len(hole) != 2:
        raise EquityError(f"need exactly 2 hole cards, got {len(hole)}")
    if len(board) not in VALID_BOARD_SIZES:
        raise EquityError(f"a board holds 0, 3, 4 or 5 cards, got {len(board)}")
    if not 1 <= opponents <= MAX_OPPONENTS:
        raise EquityError(f"opponents must be between 1 and {MAX_OPPONENTS}")
    if len(set(hole + board)) != len(hole) + len(board):
        raise EquityError("the same card appears twice between your hand and the board")


def equity(
    hole: list[int],
    board: list[int],
    opponents: int = 1,
    trials: int = 100_000,
    seed: int | None = None,
) -> EquityResult:
    """Estimate how often ``hole`` wins against ``opponents`` random hands."""
    _validate(hole, board, opponents)

    known = hole + board
    deck = np.array([c for c in range(NUM_CARDS) if c not in set(known)], dtype=np.int64)
    board_needed = 5 - len(board)
    per_trial = board_needed + 2 * opponents
    if per_trial > deck.size:
        raise EquityError(
            f"{opponents} opponents need {per_trial} more cards "
            f"but only {deck.size} remain in the deck"
        )

    rng = np.random.default_rng(seed)
    hole_arr = np.array(hole, dtype=np.int64)
    board_arr = np.array(board, dtype=np.int64)

    wins = ties = losses = 0
    equity_sum = 0.0
    done = 0
    while done < trials:
        m = min(_CHUNK, trials - done)
        done += m

        # Do not replace this with argpartition on random keys. That picks the
        # right set of cards but orders them however the partition algorithm
        # leaves them, which correlates with deck position - and since slots
        # are handed out by position, the board and the opponents then draw
        # from different parts of the deck. It overstated aces by ten points
        # against eight opponents.
        drawn = rng.permuted(np.tile(deck, (m, 1)), axis=1)[:, :per_trial]

        full_board = np.concatenate(
            [np.broadcast_to(board_arr, (m, board_arr.size)), drawn[:, :board_needed]],
            axis=1,
        )
        hero = np.concatenate([np.broadcast_to(hole_arr, (m, 2)), full_board], axis=1)
        opp_holes = drawn[:, board_needed:].reshape(m, opponents, 2)
        opp_hands = np.concatenate(
            [opp_holes, np.broadcast_to(full_board[:, None, :], (m, opponents, 5))],
            axis=2,
        )

        stacked = np.concatenate([hero[:, None, :], opp_hands], axis=1)
        scores = evaluate(stacked.reshape(m * (opponents + 1), 7)).reshape(
            m, opponents + 1
        )
        hero_score, opp_scores = scores[:, 0], scores[:, 1:]

        best_opp = opp_scores.max(axis=1)
        wins += int((hero_score > best_opp).sum())
        ties += int((hero_score == best_opp).sum())
        losses += int((hero_score < best_opp).sum())

        # Share of pot, so a three-way chop counts as a third, not half a win.
        shared_with = (opp_scores == hero_score[:, None]).sum(axis=1)
        equity_sum += float(
            np.where(hero_score >= best_opp, 1.0 / (1 + shared_with), 0.0).sum()
        )

    eq = equity_sum / trials
    return EquityResult(
        win=wins / trials,
        tie=ties / trials,
        lose=losses / trials,
        equity=eq,
        # One standard error on the pot share.
        margin_of_error=sqrt(max(eq * (1 - eq), 0.0) / trials),
        trials=trials,
        street=STREETS[len(board)],
        made_hand=describe_hand(hole, board),
        draws=find_draws(hole, board),
        prices=price_ladder(eq),
        biggest_call=biggest_call(eq),
    )


def describe_hand(hole: list[int], board: list[int]) -> str:
    cards = hole + board
    if len(cards) < 5:
        return "no hand yet"
    score = int(evaluate(np.array([cards], dtype=np.int64))[0])
    return CATEGORY_NAMES[score >> 21]


def find_draws(hole: list[int], board: list[int]) -> list[Draw]:
    """Cards still to come that would improve the hand's category.

    Cards that only pair the board are excluded - they hand every opponent
    the same hand. Pairing a hole card counts: two overcards are six outs.
    """
    cards = hole + board
    if len(board) not in (3, 4):
        return []

    current = int(evaluate(np.array([cards], dtype=np.int64))[0]) >> 21
    hole_ranks = {c >> 2 for c in hole}
    unseen = [c for c in range(NUM_CARDS) if c not in set(cards)]
    candidates = np.array([[*cards, c] for c in unseen], dtype=np.int64)
    improved = evaluate(candidates) >> 21

    by_category: dict[int, list[str]] = {}
    for card, category in zip(unseen, improved, strict=True):
        category = int(category)
        if category <= current:
            continue
        if category == ONE_PAIR and (card >> 2) not in hole_ranks:
            continue
        by_category.setdefault(category, []).append(card_str(card))

    return [
        Draw(description=CATEGORY_NAMES[cat], outs=len(cards_), cards=sorted(cards_))
        for cat, cards_ in sorted(by_category.items(), reverse=True)
    ]


@dataclass
class PotOdds:
    required_equity: float
    actual_equity: float
    margin: float
    profitable: bool
    verdict: str


def pot_odds(pot_cents: int, to_call_cents: int, actual_equity: float) -> PotOdds:
    if to_call_cents <= 0:
        raise EquityError("the amount to call must be greater than zero")
    if pot_cents < 0:
        raise EquityError("the pot cannot be negative")

    required = to_call_cents / (pot_cents + to_call_cents)
    margin = actual_equity - required
    profitable = margin > 0
    if profitable:
        verdict = (
            f"Calling is profitable: you need {required:.1%} to break even "
            f"and have {actual_equity:.1%}."
        )
    else:
        verdict = (
            f"Calling loses money: you need {required:.1%} to break even "
            f"but only have {actual_equity:.1%}."
        )
    return PotOdds(
        required_equity=required,
        actual_equity=actual_equity,
        margin=margin,
        profitable=profitable,
        verdict=verdict,
    )
