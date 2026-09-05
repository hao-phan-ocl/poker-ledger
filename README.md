# Poker Ledger

A ledger and odds calculator for a real-money home game. It tracks the money
and answers "what are my chances" — the cards and chips stay on the table.

**The ledger.** Start a game, seat players, tap a button as each buys in or
rebuys. At the end you enter everyone's chip count and it works out who pays
whom, in as few payments as possible. Results carry across nights, so you can
see who is up or down over months.

**The check that matters.** Chips are conserved: what comes off the table must
equal what went on. If the counts don't add up it says how far out you are and
refuses to produce a settlement — a plausible but wrong payment list moves real
money to the wrong people.

**The odds.** Enter your two cards and the board, pick how many opponents are
still in, and it simulates the hand fifty thousand times. It names your draws,
counts the cards that improve you, and tells you in plain English which bet
sizes are worth calling.

A game you'd rather forget can be **discarded** — kept on the record but
counting towards nobody's total — or deleted outright.

## Running it

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>, or reach it from a phone on the same wifi at
`http://<your-ip>:8000`. Tests are `uv run pytest`.

There is no login. Anyone who can reach the port can edit the ledger, which is
fine for one table in one room and wrong anywhere else. **Don't put this on the
public internet as it stands.**

Everything lives in one SQLite file, `data/poker.db`. Back it up by copying it.

## On a Raspberry Pi

An always-on Pi plus Tailscale gives you the ledger from anywhere — no hosting,
no public URL, and no login to build, because only your own devices can reach
it.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone <this repo> ~/poker-ledger && cd ~/poker-ledger
uv sync                     # fetches Python 3.12; Pi OS ships 3.11
mkdir -p ~/poker-data

sudo cp deploy/poker.service /etc/systemd/system/
sudo systemctl enable --now poker
```

It starts on boot and restarts if it crashes. `systemctl status poker` to
check, `journalctl -u poker -f` for logs.

The service points `POKER_DB` at `~/poker-data/`, outside the repo, so
`git pull` and `git clean -xdf` can't destroy the ledger.

For access away from home, install Tailscale on the Pi and your phone:

```bash
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
```

Then `http://raspberrypi:8000` works on any network.

Expect the odds calculator to take a few hundred milliseconds rather than
fifty. Lower `trials` in `app/models.py` if that bothers you.

### Backups

```bash
crontab -e
0 3 * * 0 /home/pi/poker-ledger/deploy/backup.sh >> /home/pi/backup.log 2>&1
```

A dated snapshot every Sunday, pruning anything older than 180 days. It uses
SQLite's online backup API rather than `cp`, which can catch the file mid-write
and miss recent transactions.

Those copies sit on the same disk as the database — enough if you delete a game
by mistake, useless if the SD card dies. Uncomment the `rsync` line in
`deploy/backup.sh` to get them off the machine.

## Notes

Money is integer cents, never floats. Capital counts only closed, un-discarded
games — chips still on the table aren't winnings.

The hand evaluator is bit-twiddling that can't be verified by reading it, so a
slow, obvious version lives in `app/poker/reference.py` and the tests check the
two agree across hundreds of thousands of random hands. The simulation is
checked against exact enumeration and the published equity tables.

Nothing records how anyone *plays* — no folds, calls or raises. That's the
groundwork for predicting player behaviour later, and it can't be backfilled:
hands played before it's built are gone.
