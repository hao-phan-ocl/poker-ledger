#!/usr/bin/env bash
# A dated snapshot of the ledger, pruning ones older than KEEP_DAYS.
#
#   deploy/backup.sh
#
# Weekly at 3am, via `crontab -e`:
#   0 3 * * 0 /home/pi/poker-ledger/deploy/backup.sh >> /home/pi/backup.log 2>&1
#
# Uses SQLite's online backup API rather than `cp`. A plain copy can catch the
# file mid-write, and in WAL mode the newest transactions live in poker.db-wal
# rather than poker.db - so a copy of just the one file can silently miss them.

set -euo pipefail

DB="${POKER_DB:-$HOME/poker-data/poker.db}"
DEST="${POKER_BACKUP_DIR:-$HOME/poker-backups}"
KEEP_DAYS="${POKER_BACKUP_KEEP_DAYS:-180}"
PYTHON="${POKER_PYTHON:-$HOME/poker-ledger/.venv/bin/python}"

if [ ! -f "$DB" ]; then
    echo "no database at $DB" >&2
    exit 1
fi
if [ ! -x "$PYTHON" ]; then
    echo "no python at $PYTHON - run 'uv sync' first" >&2
    exit 1
fi

mkdir -p "$DEST"
OUT="$DEST/poker-$(date +%F).db"

"$PYTHON" - "$DB" "$OUT" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
source.close()
target.close()
PY

find "$DEST" -name 'poker-*.db' -mtime "+$KEEP_DAYS" -delete

echo "$(date +'%F %T')  backed up to $OUT ($(du -h "$OUT" | cut -f1))"

# These copies sit on the same disk as the database, which covers deleting a
# game by mistake but not the card failing. Uncomment one to get them off the
# machine, which is the risk that actually loses the ledger.
#
# rsync -a "$DEST/" hao@laptop:~/poker-backups/
# rclone copy "$DEST" remote:poker-backups
