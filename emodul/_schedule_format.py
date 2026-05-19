"""Decoder for TECH globalSchedule entries.

Each controller has 5 globalSchedule slots (idx 0-4). Days are 7-element string
arrays of "0"/"1" for Pn-Nd. Intervals use minutes-of-day for start/stop and
tenths of °C for temp. Sentinel value 6100 means "unused".
"""
from __future__ import annotations

DAY_NAMES = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _intervals(raw: list[dict]) -> list[dict]:
    """Strip placeholder intervals (start > 1440) and decode to readable form."""
    out = []
    for it in raw or []:
        if it.get("start", 9999) > 1440:
            continue
        out.append(
            {
                "start": _hhmm(it["start"]),
                "stop": _hhmm(it["stop"]),
                "temp_c": it["temp"] / 10,
            }
        )
    return out


def _days_mask(mask: list[str]) -> str:
    return " ".join(d if v == "1" else "—" for d, v in zip(DAY_NAMES, mask, strict=False))


def decode_schedule(s: dict) -> dict:
    """Convert a raw TECH schedule object into a human-readable dict."""
    return {
        "index": s.get("index"),
        "id": s.get("id"),
        "name": s.get("name") or "(unnamed)",
        "p0_days": _days_mask(s.get("p0Days") or ["0"] * 7),
        "p0_intervals": _intervals(s.get("p0Intervals") or []),
        "p0_setback_c": (s.get("p0SetbackTemp") or 0) / 10,
        "p1_days": _days_mask(s.get("p1Days") or ["0"] * 7),
        "p1_intervals": _intervals(s.get("p1Intervals") or []),
        "p1_setback_c": (s.get("p1SetbackTemp") or 0) / 10,
    }


def zones_using_schedule(snapshot: dict, sched_idx: int) -> list[str]:
    """Names of zones currently referencing this globalSchedule index."""
    from emodul.format import flatten_zones

    rows = flatten_zones(snapshot)
    return [
        r["name"]
        for r in rows
        if r.get("mode") == "globalSchedule" and r.get("schedule_index") == sched_idx
    ]
