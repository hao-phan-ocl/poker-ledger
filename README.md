# Poker Ledger

A ledger and odds calculator for a home poker game.

- **Games:** seat players, record buy-ins and cash-outs, and get who pays whom
  at the end. If the chips don't add up, it says how far out you are instead
  of settling.
- **Players:** each player's results across all closed games.
- **Odds:** enter your cards and the board to see your chance of winning.

## Running it

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>, or `http://<your-ip>:8000` from a phone on the
same wifi. Tests are `uv run pytest`.

To update: `git pull`, then stop the server (Ctrl+C) and start it again.

## Good to know

- There is no login: anyone who can reach the port can edit the ledger.
- Everything is stored in one file, `data/poker.db`. Back it up by copying it.
