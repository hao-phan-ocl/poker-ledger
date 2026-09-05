-- STRICT so a text value cannot land in a cents column.

CREATE TABLE IF NOT EXISTS player (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS game (
    id                    INTEGER PRIMARY KEY,
    label                 TEXT NOT NULL,
    location              TEXT NOT NULL DEFAULT '',
    currency              TEXT NOT NULL DEFAULT 'EUR',
    small_blind_cents     INTEGER NOT NULL DEFAULT 0,
    big_blind_cents       INTEGER NOT NULL DEFAULT 0,
    default_buy_in_cents  INTEGER NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'live'
                          CHECK (status IN ('live', 'closed')),
    started_at            TEXT NOT NULL,
    ended_at              TEXT
    -- voided/void_reason are added by migration 2; this file is migration 1
    -- and must keep describing the schema as it first shipped.
) STRICT;

CREATE TABLE IF NOT EXISTS game_player (
    game_id    INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
    player_id  INTEGER NOT NULL REFERENCES player(id) ON DELETE RESTRICT,
    seat       INTEGER,
    PRIMARY KEY (game_id, player_id)
) STRICT;

-- Append-only: money never moves except by adding a row.
CREATE TABLE IF NOT EXISTS txn (
    id            INTEGER PRIMARY KEY,
    game_id       INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
    player_id     INTEGER NOT NULL REFERENCES player(id) ON DELETE RESTRICT,
    kind          TEXT NOT NULL
                  CHECK (kind IN ('buy_in', 'cash_out', 'adjustment')),
    amount_cents  INTEGER NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS txn_by_game ON txn(game_id);
CREATE INDEX IF NOT EXISTS txn_by_player ON txn(player_id);
