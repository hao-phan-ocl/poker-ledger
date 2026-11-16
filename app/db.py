import sqlite3
import threading
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
    # One currency, one symbol. Amounts were stored as bare cents with the
    # currency only ever used to pick a symbol, so nothing needs converting.
    """
    ALTER TABLE game DROP COLUMN currency;
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


# Every request opens a connection and migrates. Without this, two requests
# arriving together on an old database would both run the same migration.
_migrate_lock = threading.Lock()


def migrate(conn: sqlite3.Connection) -> int:
    with _migrate_lock:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index in range(version, len(MIGRATIONS)):
            # executescript commits on its own, so `with conn` cannot make a
            # migration atomic. Wrap each in its own transaction, version bump
            # included: a migration that fails halfway leaves no trace, and the
            # next start retries it cleanly instead of hitting a half-applied
            # schema. (PRAGMA takes no bound parameters; the value is an index.)
            try:
                conn.executescript(
                    "BEGIN;\n"
                    + MIGRATIONS[index]
                    + f"\n;\nPRAGMA user_version = {index + 1};\nCOMMIT;"
                )
            except Exception:
                conn.rollback()
                raise
    return len(MIGRATIONS)
