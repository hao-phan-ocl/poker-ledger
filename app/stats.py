"""Lifetime results per player.

Only closed, un-voided games count - chips still on the table are not
winnings, and a voided game is one that should never have counted.
"""

import sqlite3
from dataclasses import dataclass, field


@dataclass
class SessionResult:
    game_id: int
    label: str
    played_at: str
    buy_in_cents: int
    cash_out_cents: int
    net_cents: int
    running_capital_cents: int


@dataclass
class Streak:
    kind: str  # "winning", "losing", "even" or "none"
    length: int


@dataclass
class PlayerStats:
    player_id: int
    name: str
    games_played: int
    total_buy_in_cents: int
    total_cash_out_cents: int
    capital_cents: int
    winning_sessions: int
    losing_sessions: int
    best_night_cents: int
    worst_night_cents: int
    average_net_cents: int
    roi: float | None
    streak: Streak
    sessions: list[SessionResult] = field(default_factory=list)


_SESSION_QUERY = """
    SELECT p.id            AS player_id,
           p.name          AS name,
           g.id            AS game_id,
           g.label         AS label,
           COALESCE(g.ended_at, g.started_at) AS played_at,
           COALESCE(SUM(CASE WHEN t.kind = 'buy_in'
                             THEN t.amount_cents END), 0) AS buy_in,
           COALESCE(SUM(CASE WHEN t.kind = 'cash_out'
                             THEN t.amount_cents END), 0) AS cash_out,
           COALESCE(SUM(CASE WHEN t.kind = 'adjustment'
                             THEN t.amount_cents END), 0) AS adjustment
      FROM game g
      JOIN game_player gp ON gp.game_id = g.id
      JOIN player p       ON p.id = gp.player_id
      LEFT JOIN txn t     ON t.game_id = g.id AND t.player_id = p.id
     WHERE g.status = 'closed' AND g.voided = 0
     GROUP BY g.id, p.id
     ORDER BY played_at, g.id
"""


def _streak(nets: list[int]) -> Streak:
    """The current run of winning or losing nights, counted back from the latest."""
    if not nets:
        return Streak(kind="none", length=0)
    latest = nets[-1]
    kind = "winning" if latest > 0 else "losing" if latest < 0 else "even"
    length = 0
    for net in reversed(nets):
        same = (net > 0) if latest > 0 else (net < 0) if latest < 0 else (net == 0)
        if not same:
            break
        length += 1
    return Streak(kind=kind, length=length)


def all_player_stats(conn: sqlite3.Connection) -> list[PlayerStats]:
    rows = conn.execute(_SESSION_QUERY).fetchall()

    by_player: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_player.setdefault(row["player_id"], []).append(row)

    stats: list[PlayerStats] = []
    for player_id, sessions in by_player.items():
        running = 0
        history: list[SessionResult] = []
        for row in sessions:
            net = row["cash_out"] + row["adjustment"] - row["buy_in"]
            running += net
            history.append(
                SessionResult(
                    game_id=row["game_id"],
                    label=row["label"],
                    played_at=row["played_at"],
                    buy_in_cents=row["buy_in"],
                    cash_out_cents=row["cash_out"],
                    net_cents=net,
                    running_capital_cents=running,
                )
            )

        nets = [s.net_cents for s in history]
        total_in = sum(s.buy_in_cents for s in history)
        stats.append(
            PlayerStats(
                player_id=player_id,
                name=sessions[0]["name"],
                games_played=len(history),
                total_buy_in_cents=total_in,
                total_cash_out_cents=sum(s.cash_out_cents for s in history),
                capital_cents=running,
                winning_sessions=sum(1 for n in nets if n > 0),
                losing_sessions=sum(1 for n in nets if n < 0),
                best_night_cents=max(nets),
                worst_night_cents=min(nets),
                # Integer division: money never becomes a float.
                average_net_cents=running // len(nets),
                roi=(running / total_in) if total_in else None,
                streak=_streak(nets),
                sessions=history,
            )
        )

    stats.sort(key=lambda s: s.capital_cents, reverse=True)
    return stats


def player_stats(conn: sqlite3.Connection, player_id: int) -> PlayerStats | None:
    for stats in all_player_stats(conn):
        if stats.player_id == player_id:
            return stats
    return None
