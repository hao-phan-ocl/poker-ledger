# Poker Ledger

A ledger and odds calculator for a home poker game.

- **Games:** seat players, record buy-ins and cash-outs, and get who pays whom
  at the end. If the chips don't add up, it says how far out you are instead
  of settling.
- **Players:** each player's results across all closed games.
- **Odds:** enter your cards and the board to see your chance of winning.

## Running it

### On a computer

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

uv installs everything the first time. Tests are `uv run pytest`.

### On Android (Termux)

numpy can't be built on Termux, so the app uses packages installed globally
instead of the versions in `uv.lock`. Once:

```bash
pkg install python python-numpy
pip install fastapi uvicorn
uv venv --system-site-packages
```

Then to start it:

```bash
uv run --no-sync python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--no-sync` stops uv from installing `uv.lock`, which would try to build numpy
and fail. If `pip install` fails on pydantic-core, run `pkg install rust` and
`export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)`, then retry.

### Either way

Open <http://localhost:8000>, or `http://<your-ip>:8000` from another device on
the same wifi. Use another `--port` if 8000 is taken.

To update: `git pull`, then stop the server (Ctrl+C) and start it again.

## Good to know

- There is no login: anyone who can reach the port can edit the ledger.
- Everything is stored in one file, `data/poker.db`. Back it up by copying it.
