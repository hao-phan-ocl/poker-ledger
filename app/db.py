import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "poker.db"

_SCHEMA = (Path(__file__).resolve().parent / "schema.sql").read_text()

# Append only. Editing an existing entry corrupts databases that already ran it.
MIGRATIONS: list[str] = [
    _SCHEMA,
    """
    ALTER TABLE game ADD COLUMN voided INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE game ADD COLUMN void_reason TEXT NOT NULL DEFAULT '';
    """,
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # SQLite leaves foreign keys off unless asked, per connection.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        with conn:
            conn.executescript(MIGRATIONS[index])
            # PRAGMA takes no bound parameters; the value is a loop index.
            conn.execute(f"PRAGMA user_version = {index + 1}")
    return len(MIGRATIONS)
