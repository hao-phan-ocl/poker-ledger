"""Buy-ins, cash-outs and settlement. All money is integer cents, never float."""

import sqlite3
from dataclasses import dataclass

from .db import utcnow

BUY_IN = "buy_in"
CASH_OUT = "cash_out"
ADJUSTMENT = "adjustment"
KINDS = (BUY_IN, CASH_OUT, ADJUSTMENT)

CLOSED = "closed"


class LedgerError(ValueError):
    """Raised when an operation would leave the books in a bad state."""


def format_money(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def create_player(conn: sqlite3.Connection, name: str, notes: str = "") -> int:
    name = name.strip()
    if not name:
        raise LedgerError("a player needs a name")
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO player (name, notes, created_at) VALUES (?, ?, ?)",
                (name, notes, utcnow()),
            )
    except sqlite3.IntegrityError as exc:
        raise LedgerError(f"there is already a player called {name!r}") from exc
    return int(cur.lastrowid)


def list_players(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM player ORDER BY name COLLATE NOCASE").fetchall()


def get_player(conn: sqlite3.Connection, player_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM player WHERE id = ?", (player_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no player with id {player_id}")
    return row


def create_game(
    conn: sqlite3.Connection,
    label: str,
    location: str = "",
    small_blind_cents: int = 0,
    big_blind_cents: int = 0,
    default_buy_in_cents: int = 0,
) -> int:
    label = label.strip()
    if not label:
        raise LedgerError("a game needs a label")
    for name, value in (
        ("small blind", small_blind_cents),
        ("big blind", big_blind_cents),
        ("default buy-in", default_buy_in_cents),
    ):
        if value < 0:
            raise LedgerError(f"{name} cannot be negative")
    with conn:
        cur = conn.execute(
            """INSERT INTO game (label, location, small_blind_cents,
                                 big_blind_cents, default_buy_in_cents,
                                 status, started_at)
               VALUES (?, ?, ?, ?, ?, 'live', ?)""",
            (
                label,
                location,
                small_blind_cents,
                big_blind_cents,
                default_buy_in_cents,
                utcnow(),
            ),
        )
    return int(cur.lastrowid)


def get_game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM game WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no game with id {game_id}")
    return row


def list_games(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT g.*,
                  (SELECT COUNT(*) FROM game_player gp WHERE gp.game_id = g.id)
                      AS player_count,
                  (SELECT COALESCE(SUM(amount_cents), 0) FROM txn
                    WHERE txn.game_id = g.id AND kind = 'buy_in') AS pot_cents
             FROM game g
         -- Anything still running comes first, so a game left open is the
         -- first thing you see rather than something you scroll past.
         ORDER BY (g.status = 'live' AND g.voided = 0) DESC,
                  g.started_at DESC, g.id DESC"""
    ).fetchall()


def seat_player(
    conn: sqlite3.Connection, game_id: int, player_id: int, seat: int | None = None
) -> None:
    game = get_game(conn, game_id)
    if game["status"] == CLOSED:
        raise LedgerError("this game is closed - reopen it before seating anyone")
    get_player(conn, player_id)
    with conn:
        conn.execute(
            """INSERT INTO game_player (game_id, player_id, seat) VALUES (?, ?, ?)
               ON CONFLICT (game_id, player_id) DO UPDATE SET seat = excluded.seat""",
            (game_id, player_id, seat),
        )


def unseat_player(conn: sqlite3.Connection, game_id: int, player_id: int) -> None:
    count = conn.execute(
        "SELECT COUNT(*) FROM txn WHERE game_id = ? AND player_id = ?",
        (game_id, player_id),
    ).fetchone()[0]
    if count:
        raise LedgerError(
            "this player already has transactions in the game - "
            "delete those first if they were seated by mistake"
        )
    with conn:
        conn.execute(
            "DELETE FROM game_player WHERE game_id = ? AND player_id = ?",
            (game_id, player_id),
        )


def close_game(conn: sqlite3.Connection, game_id: int, force: bool = False) -> None:
    summary = game_summary(conn, game_id)
    if not summary.balanced and not force:
        raise LedgerError(summary.balance_message)
    with conn:
        conn.execute(
            "UPDATE game SET status = 'closed', ended_at = ? WHERE id = ?",
            (utcnow(), game_id),
        )


def reopen_game(conn: sqlite3.Connection, game_id: int) -> None:
    game = get_game(conn, game_id)
    if game["voided"]:
        raise LedgerError("this game is voided - restore it before reopening")
    with conn:
        conn.execute(
            "UPDATE game SET status = 'live', ended_at = NULL WHERE id = ?", (game_id,)
        )


def void_game(conn: sqlite3.Connection, game_id: int, reason: str = "") -> None:
    """Keep the rows, but stop the game counting towards capital or stats."""
    get_game(conn, game_id)
    with conn:
        conn.execute(
            "UPDATE game SET voided = 1, void_reason = ? WHERE id = ?",
            (reason.strip(), game_id),
        )


def restore_game(conn: sqlite3.Connection, game_id: int) -> None:
    get_game(conn, game_id)
    with conn:
        conn.execute(
            "UPDATE game SET voided = 0, void_reason = '' WHERE id = ?", (game_id,)
        )


def delete_game(conn: sqlite3.Connection, game_id: int) -> None:
    """Erase a game and everything recorded against it. Not reversible.

    Voiding is usually the better answer, since it keeps the history. This is
    for a game that should never have existed at all.
    """
    get_game(conn, game_id)
    # game_player and txn both cascade from game.
    with conn:
        conn.execute("DELETE FROM game WHERE id = ?", (game_id,))


def record(
    conn: sqlite3.Connection,
    game_id: int,
    player_id: int,
    kind: str,
    amount_cents: int,
    note: str = "",
) -> int:
    if kind not in KINDS:
        raise LedgerError(f"{kind!r} is not one of {', '.join(KINDS)}")
    game = get_game(conn, game_id)
    if game["status"] == CLOSED:
        raise LedgerError("this game is closed - reopen it to make changes")
    if game["voided"]:
        raise LedgerError("this game is voided - restore it before recording anything")

    seated = conn.execute(
        "SELECT 1 FROM game_player WHERE game_id = ? AND player_id = ?",
        (game_id, player_id),
    ).fetchone()
    if seated is None:
        raise LedgerError("that player is not in this game")

    if kind == BUY_IN and amount_cents <= 0:
        raise LedgerError("a buy-in must be more than zero")
    # A cash-out of zero is how a player who busted is recorded, so it has to
    # be allowed; only a negative one is nonsense.
    if kind == CASH_OUT and amount_cents < 0:
        raise LedgerError("a cash-out cannot be negative")
    if kind == ADJUSTMENT and amount_cents == 0:
        raise LedgerError("an adjustment of zero changes nothing")

    with conn:
        cur = conn.execute(
            """INSERT INTO txn (game_id, player_id, kind, amount_cents, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, player_id, kind, amount_cents, note, utcnow()),
        )
    return int(cur.lastrowid)


def buy_in(conn, game_id: int, player_id: int, amount_cents: int, note: str = "") -> int:
    return record(conn, game_id, player_id, BUY_IN, amount_cents, note)


def cash_out(
    conn, game_id: int, player_id: int, amount_cents: int, note: str = ""
) -> int:
    return record(conn, game_id, player_id, CASH_OUT, amount_cents, note)


def delete_txn(conn: sqlite3.Connection, txn_id: int) -> None:
    row = conn.execute("SELECT game_id FROM txn WHERE id = ?", (txn_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no transaction with id {txn_id}")
    if get_game(conn, row["game_id"])["status"] == CLOSED:
        raise LedgerError("this game is closed - reopen it to make changes")
    with conn:
        conn.execute("DELETE FROM txn WHERE id = ?", (txn_id,))


def game_transactions(conn: sqlite3.Connection, game_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.*, p.name AS player_name
             FROM txn t JOIN player p ON p.id = t.player_id
            WHERE t.game_id = ?
         ORDER BY t.created_at, t.id""",
        (game_id,),
    ).fetchall()


@dataclass
class PlayerResult:
    player_id: int
    name: str
    buy_in_cents: int
    cash_out_cents: int
    adjustment_cents: int
    net_cents: int
    cashed_out: bool


@dataclass
class GameSummary:
    game_id: int
    label: str
    status: str
    results: list[PlayerResult]
    total_buy_in_cents: int
    total_cash_out_cents: int
    total_adjustment_cents: int
    discrepancy_cents: int
    balanced: bool
    balance_message: str
    awaiting_cash_out: list[str]


def game_summary(conn: sqlite3.Connection, game_id: int) -> GameSummary:
    game = get_game(conn, game_id)
    rows = conn.execute(
        """SELECT p.id, p.name,
                  COALESCE(SUM(CASE WHEN t.kind = 'buy_in'
                                    THEN t.amount_cents END), 0) AS buy_in,
                  COALESCE(SUM(CASE WHEN t.kind = 'cash_out'
                                    THEN t.amount_cents END), 0) AS cash_out,
                  COALESCE(SUM(CASE WHEN t.kind = 'adjustment'
                                    THEN t.amount_cents END), 0) AS adjustment,
                  COUNT(CASE WHEN t.kind = 'cash_out' THEN 1 END) AS cash_out_count
             FROM game_player gp
             JOIN player p ON p.id = gp.player_id
             LEFT JOIN txn t ON t.player_id = p.id AND t.game_id = gp.game_id
            WHERE gp.game_id = ?
         GROUP BY p.id, p.name
         ORDER BY p.name COLLATE NOCASE""",
        (game_id,),
    ).fetchall()

    results = [
        PlayerResult(
            player_id=r["id"],
            name=r["name"],
            buy_in_cents=r["buy_in"],
            cash_out_cents=r["cash_out"],
            adjustment_cents=r["adjustment"],
            net_cents=r["cash_out"] + r["adjustment"] - r["buy_in"],
            cashed_out=bool(r["cash_out_count"]),
        )
        for r in rows
    ]

    total_in = sum(r.buy_in_cents for r in results)
    total_out = sum(r.cash_out_cents for r in results)
    total_adj = sum(r.adjustment_cents for r in results)
    # Chips are conserved: what comes off the table must equal what went on.
    discrepancy = total_out + total_adj - total_in

    if discrepancy == 0:
        message = "The books balance."
    elif discrepancy < 0:
        message = (
            f"The table is {format_money(-discrepancy)} short - "
            f"chips are missing or a stack was miscounted. Recount before settling."
        )
    else:
        message = (
            f"The table is {format_money(discrepancy)} over - "
            f"more was counted out than was ever bought in. Recount before settling."
        )

    return GameSummary(
        game_id=game_id,
        label=game["label"],
        status=game["status"],
        results=results,
        total_buy_in_cents=total_in,
        total_cash_out_cents=total_out,
        total_adjustment_cents=total_adj,
        discrepancy_cents=discrepancy,
        balanced=discrepancy == 0,
        balance_message=message,
        awaiting_cash_out=[r.name for r in results if not r.cashed_out],
    )


@dataclass
class Payment:
    from_player_id: int
    from_name: str
    to_player_id: int
    to_name: str
    amount_cents: int


@dataclass
class Settlement:
    balanced: bool
    message: str
    payments: list[Payment]


def settle(conn: sqlite3.Connection, game_id: int) -> Settlement:
    """Who pays whom, in at most n-1 payments.

    Returns nothing for books that do not balance: a plausible but wrong
    payment list would move real money to the wrong people.
    """
    summary = game_summary(conn, game_id)
    if not summary.balanced:
        return Settlement(
            balanced=False,
            message=summary.balance_message,
            payments=[],
        )

    debtors = sorted(
        ((r, -r.net_cents) for r in summary.results if r.net_cents < 0),
        key=lambda pair: pair[1],
        reverse=True,
    )
    creditors = sorted(
        ((r, r.net_cents) for r in summary.results if r.net_cents > 0),
        key=lambda pair: pair[1],
        reverse=True,
    )

    payments: list[Payment] = []
    i = j = 0
    owed = [amount for _, amount in debtors]
    due = [amount for _, amount in creditors]
    while i < len(debtors) and j < len(creditors):
        amount = min(owed[i], due[j])
        if amount > 0:
            payments.append(
                Payment(
                    from_player_id=debtors[i][0].player_id,
                    from_name=debtors[i][0].name,
                    to_player_id=creditors[j][0].player_id,
                    to_name=creditors[j][0].name,
                    amount_cents=amount,
                )
            )
        owed[i] -= amount
        due[j] -= amount
        if owed[i] == 0:
            i += 1
        if due[j] == 0:
            j += 1

    if not payments:
        message = "Everyone finished level - nothing to settle."
    else:
        plural = "s" if len(payments) > 1 else ""
        message = f"{len(payments)} payment{plural} settles the night."
    return Settlement(balanced=True, message=message, payments=payments)
