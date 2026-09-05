"""JSON API and the static page, from one process.

No authentication: anyone who can reach the port can edit the ledger.
"""

import csv
import io
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import ledger, stats
from .db import DEFAULT_DB_PATH, connect
from .models import (
    CloseRequest,
    NewGame,
    NewPlayer,
    NewTransaction,
    OddsRequest,
    SeatRequest,
    VoidRequest,
)
from .poker.cards import CardError, parse_cards
from .poker.equity import EquityError, equity, pot_odds

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DB_PATH = Path(os.environ.get("POKER_DB", DEFAULT_DB_PATH))

app = FastAPI(
    title="Poker Ledger",
    description="Buy-ins, settlement and hand equity for a home game.",
    version="0.1.0",
)


def get_conn() -> Iterator[sqlite3.Connection]:
    # Per request, rather than sharing one across FastAPI's worker threads.
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _rows(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ledger.LedgerError, EquityError, CardError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/players")
def list_players(conn=Depends(get_conn)):
    return _rows(ledger.list_players(conn))


@app.post("/api/players", status_code=201)
def create_player(body: NewPlayer, conn=Depends(get_conn)):
    player_id = _guard(ledger.create_player, conn, body.name, body.notes)
    return dict(ledger.get_player(conn, player_id))


@app.get("/api/players/stats")
def player_stats(conn=Depends(get_conn)):
    return [asdict(s) for s in stats.all_player_stats(conn)]


@app.get("/api/games")
def list_games(conn=Depends(get_conn)):
    return _rows(ledger.list_games(conn))


@app.post("/api/games", status_code=201)
def create_game(body: NewGame, conn=Depends(get_conn)):
    game_id = _guard(
        ledger.create_game,
        conn,
        body.label,
        body.location,
        body.small_blind_cents,
        body.big_blind_cents,
        body.default_buy_in_cents,
    )
    return dict(ledger.get_game(conn, game_id))


@app.get("/api/games/{game_id}")
def game_detail(game_id: int, conn=Depends(get_conn)):
    game = _guard(ledger.get_game, conn, game_id)
    return {
        "game": dict(game),
        "summary": asdict(ledger.game_summary(conn, game_id)),
        "transactions": _rows(ledger.game_transactions(conn, game_id)),
    }


@app.post("/api/games/{game_id}/players", status_code=201)
def seat_player(game_id: int, body: SeatRequest, conn=Depends(get_conn)):
    _guard(ledger.seat_player, conn, game_id, body.player_id, body.seat)
    return asdict(ledger.game_summary(conn, game_id))


@app.delete("/api/games/{game_id}/players/{player_id}")
def unseat_player(game_id: int, player_id: int, conn=Depends(get_conn)):
    _guard(ledger.unseat_player, conn, game_id, player_id)
    return asdict(ledger.game_summary(conn, game_id))


@app.post("/api/games/{game_id}/transactions", status_code=201)
def add_transaction(game_id: int, body: NewTransaction, conn=Depends(get_conn)):
    # The id comes back so the page can offer an undo for the entry just made.
    txn_id = _guard(
        ledger.record,
        conn,
        game_id,
        body.player_id,
        body.kind,
        body.amount_cents,
        body.note,
    )
    return {
        "transaction_id": txn_id,
        "summary": asdict(ledger.game_summary(conn, game_id)),
    }


@app.delete("/api/transactions/{txn_id}")
def delete_transaction(txn_id: int, conn=Depends(get_conn)):
    _guard(ledger.delete_txn, conn, txn_id)
    return {"deleted": txn_id}


@app.get("/api/games/{game_id}/settlement")
def settlement(game_id: int, conn=Depends(get_conn)):
    _guard(ledger.get_game, conn, game_id)
    return asdict(ledger.settle(conn, game_id))


@app.post("/api/games/{game_id}/close")
def close_game(game_id: int, body: CloseRequest, conn=Depends(get_conn)):
    _guard(ledger.close_game, conn, game_id, body.force)
    return dict(ledger.get_game(conn, game_id))


@app.post("/api/games/{game_id}/reopen")
def reopen_game(game_id: int, conn=Depends(get_conn)):
    _guard(ledger.reopen_game, conn, game_id)
    return dict(ledger.get_game(conn, game_id))


@app.post("/api/games/{game_id}/void")
def void_game(game_id: int, body: VoidRequest, conn=Depends(get_conn)):
    _guard(ledger.void_game, conn, game_id, body.reason)
    return dict(ledger.get_game(conn, game_id))


@app.post("/api/games/{game_id}/restore")
def restore_game(game_id: int, conn=Depends(get_conn)):
    _guard(ledger.restore_game, conn, game_id)
    return dict(ledger.get_game(conn, game_id))


@app.delete("/api/games/{game_id}")
def delete_game(game_id: int, conn=Depends(get_conn)):
    _guard(ledger.delete_game, conn, game_id)
    return {"deleted": game_id}


@app.post("/api/odds")
def odds(body: OddsRequest):
    hole = _guard(parse_cards, body.hole)
    board = _guard(parse_cards, body.board)
    # Each list is checked for internal duplicates; overlap is not.
    if set(hole) & set(board):
        raise HTTPException(
            status_code=400, detail="a card cannot be in your hand and on the board"
        )

    result = _guard(equity, hole, board, body.opponents, body.trials)
    payload = asdict(result)
    if body.to_call_cents:
        payload["pot_odds"] = asdict(
            _guard(pot_odds, body.pot_cents or 0, body.to_call_cents, result.equity)
        )
    return payload


@app.get("/api/export.json")
def export_json(conn=Depends(get_conn)):
    return {
        "players": _rows(ledger.list_players(conn)),
        "games": _rows(ledger.list_games(conn)),
        "transactions": _rows(
            conn.execute(
                """SELECT t.*, p.name AS player_name, g.label AS game_label
                     FROM txn t
                     JOIN player p ON p.id = t.player_id
                     JOIN game g   ON g.id = t.game_id
                 ORDER BY t.created_at, t.id"""
            ).fetchall()
        ),
    }


@app.get("/api/export.csv")
def export_csv(conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT g.label AS game, g.started_at, g.status,
                  p.name AS player, t.kind, t.amount_cents, t.note, t.created_at
             FROM txn t
             JOIN player p ON p.id = t.player_id
             JOIN game g   ON g.id = t.game_id
         ORDER BY g.started_at, t.created_at, t.id"""
    ).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "game",
            "started_at",
            "status",
            "player",
            "kind",
            "amount",
            "note",
            "recorded_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["game"],
                row["started_at"],
                row["status"],
                row["player"],
                row["kind"],
                f"{row['amount_cents'] / 100:.2f}",
                row["note"],
                row["created_at"],
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="poker-ledger.csv"'},
    )


@app.get("/health")
def health():
    return {"status": "ok", "database": str(DB_PATH)}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
