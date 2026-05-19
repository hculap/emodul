"""SQLite event log for relay/tile state transitions and zone-setpoint changes."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def default_db_path() -> Path:
    """Cross-platform default: ~/.local/state/emodul/state.db (overridable via env)."""
    override = os.environ.get("EMODUL_STATE_DIR")
    base = Path(override) if override else Path.home() / ".local" / "state" / "emodul"
    base.mkdir(parents=True, exist_ok=True)
    return base / "state.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS tile_events (
  ts        INTEGER NOT NULL,
  udid      TEXT    NOT NULL,
  tile_id   INTEGER NOT NULL,
  name      TEXT,
  state     INTEGER NOT NULL,
  PRIMARY KEY (ts, udid, tile_id)
);
CREATE INDEX IF NOT EXISTS ix_tile_events_tile ON tile_events (udid, tile_id, ts);

CREATE TABLE IF NOT EXISTS zone_events (
  ts          INTEGER NOT NULL,
  udid        TEXT    NOT NULL,
  zone_id     INTEGER NOT NULL,
  name        TEXT,
  set_c       REAL,
  current_c   REAL,
  mode        TEXT,
  relay       TEXT,
  PRIMARY KEY (ts, udid, zone_id)
);
CREATE INDEX IF NOT EXISTS ix_zone_events_zone ON zone_events (udid, zone_id, ts);

CREATE TABLE IF NOT EXISTS run_log (
  ts        INTEGER NOT NULL,
  level     TEXT    NOT NULL,
  message   TEXT    NOT NULL
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def latest_tile_state(conn: sqlite3.Connection, udid: str, tile_id: int) -> int | None:
    row = conn.execute(
        "SELECT state FROM tile_events WHERE udid=? AND tile_id=? ORDER BY ts DESC LIMIT 1",
        (udid, tile_id),
    ).fetchone()
    return row[0] if row else None


def latest_zone_setpoint(conn: sqlite3.Connection, udid: str, zone_id: int) -> tuple[float | None, str | None]:
    row = conn.execute(
        "SELECT set_c, mode FROM zone_events WHERE udid=? AND zone_id=? ORDER BY ts DESC LIMIT 1",
        (udid, zone_id),
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def insert_tile_event(
    conn: sqlite3.Connection, ts: int, udid: str, tile_id: int, name: str, state: int
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tile_events (ts, udid, tile_id, name, state) VALUES (?,?,?,?,?)",
        (ts, udid, tile_id, name, state),
    )


def insert_zone_event(
    conn: sqlite3.Connection,
    ts: int,
    udid: str,
    zone_id: int,
    name: str,
    set_c: float | None,
    current_c: float | None,
    mode: str | None,
    relay: str | None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO zone_events "
        "(ts, udid, zone_id, name, set_c, current_c, mode, relay) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ts, udid, zone_id, name, set_c, current_c, mode, relay),
    )


def log(conn: sqlite3.Connection, level: str, message: str, ts: int) -> None:
    conn.execute("INSERT INTO run_log (ts, level, message) VALUES (?,?,?)", (ts, level, message))
