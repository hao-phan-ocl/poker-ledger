"""A card is an int 0-51: rank = card >> 2 (0 = deuce, 12 = ace), suit = card & 3."""

RANKS = "23456789TJQKA"
SUITS = "cdhs"

NUM_CARDS = 52

_RANK_INDEX = {ch: i for i, ch in enumerate(RANKS)}
_SUIT_INDEX = {ch: i for i, ch in enumerate(SUITS)}


class CardError(ValueError):
    """Raised when a card string cannot be parsed."""


def rank_of(card: int) -> int:
    return card >> 2


def suit_of(card: int) -> int:
    return card & 3


def make_card(rank: int, suit: int) -> int:
    return (rank << 2) | suit


def parse_card(text: str) -> int:
    """Parse "As", "th", "2C" - rank first, then suit."""
    s = text.strip()
    if len(s) != 2:
        raise CardError(f"{text!r} is not a card - expected two characters like 'As'")
    rank_ch, suit_ch = s[0].upper(), s[1].lower()
    if rank_ch not in _RANK_INDEX:
        raise CardError(f"{text!r} has an unknown rank {s[0]!r} - use one of {RANKS}")
    if suit_ch not in _SUIT_INDEX:
        raise CardError(f"{text!r} has an unknown suit {s[1]!r} - use one of {SUITS}")
    return make_card(_RANK_INDEX[rank_ch], _SUIT_INDEX[suit_ch])


def card_str(card: int) -> str:
    return RANKS[rank_of(card)] + SUITS[suit_of(card)]


def parse_cards(texts) -> list[int]:
    # A duplicate card would skew every equity number computed from it rather
    # than failing, so reject it here.
    cards = [parse_card(t) for t in texts]
    seen: set[int] = set()
    for original, card in zip(texts, cards, strict=True):
        if card in seen:
            raise CardError(f"{original!r} appears more than once")
        seen.add(card)
    return cards
