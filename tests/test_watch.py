"""Watcher storage: periodic zone samples next to the change-only event tables."""
from __future__ import annotations

import sqlite3

from emodul import storage
from emodul.commands.watch import _record_zone_samples, _record_zones, _watcher_command


def _snapshot(current: int, relay: str = "on") -> dict:
    return {
        "zones": {
            "elements": [
                {
                    "zone": {
                        "id": 9002,
                        "zoneState": "noAlarm",
                        "currentTemperature": current,
                        "setTemperature": 220,
                        "humidity": 0,
                        "flags": {"relayState": relay},
                    },
                    "description": {"name": "Salon"},
                    "mode": {"mode": "constantTemp"},
                },
                None,
                {
                    "zone": {"id": 9019, "zoneState": "zoneUnregistered"},
                    "description": {"name": "Strefa 3"},
                },
            ]
        }
    }


def test_samples_every_visible_zone_even_without_changes(tmp_path) -> None:
    conn = storage.open_db(tmp_path / "state.db")
    _record_zone_samples(conn, 1000, "abc", _snapshot(216))
    _record_zone_samples(conn, 1600, "abc", _snapshot(216))
    rows = conn.execute(
        "SELECT ts, zone_id, name, current_c, set_c, humidity, relay FROM zone_samples ORDER BY ts"
    ).fetchall()
    # humidity 0 means "no sensor"; the unregistered zone and the null slot are skipped
    assert rows == [
        (1000, 9002, "Salon", 21.6, 22.0, None, "on"),
        (1600, 9002, "Salon", 21.6, 22.0, None, "on"),
    ]


def test_zone_events_stay_change_only(tmp_path) -> None:
    conn = storage.open_db(tmp_path / "state.db")
    _record_zones(conn, 1000, "abc", _snapshot(216))
    _record_zones(conn, 1060, "abc", _snapshot(218))
    _record_zones(conn, 1120, "abc", _snapshot(218, relay="off"))
    assert conn.execute("SELECT ts FROM zone_events ORDER BY ts").fetchall() == [(1000,), (1120,)]


def test_open_db_adds_samples_table_to_an_existing_db(tmp_path) -> None:
    path = tmp_path / "state.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE zone_events (ts INTEGER, udid TEXT, zone_id INTEGER)")
    old.execute("INSERT INTO zone_events VALUES (1, 'abc', 9002)")
    old.commit()
    old.close()
    conn = storage.open_db(path)
    assert conn.execute("SELECT COUNT(*) FROM zone_events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM zone_samples").fetchone()[0] == 0


def test_service_command_passes_the_sample_cadence(tmp_path) -> None:
    cmd = _watcher_command(60, tmp_path / "state.db", 900)
    assert cmd[-2:] == ["--sample-every", "900"]
