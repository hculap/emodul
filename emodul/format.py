"""Output helpers: unit conversion, zone/tile flattening, table rendering."""
from __future__ import annotations

import json
import sys
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def temp_from_api(v: int | float | None) -> float | None:
    if v is None:
        return None
    return round(v / 10.0, 1)


def temp_to_api(celsius: float) -> int:
    return int(round(celsius * 10))


def dump_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _hvac_action(relay: str | None, algorithm: str | None) -> str:
    """Derived HVAC action from (relay, algorithm) — what the zone is actually doing.

    Borrowed from the Home Assistant tech-controllers integration (`climate.py:154-164`).
    """
    if relay == "on" and algorithm == "heating":
        return "heating"
    if relay == "on" and algorithm == "cooling":
        return "cooling"
    if relay == "off":
        return "idle"
    return "off"


def flatten_zones(module: dict, include_hidden: bool = False) -> list[dict]:
    """Pull the meaningful fields out of /modules/{udid}.zones.elements[].

    Defensive filter (borrowed from HA `tech.py:253-261`): skip null array slots,
    invisible zones, and zones in `zoneUnregistered` state. Pass `include_hidden=True`
    to override.
    """
    elements = (module.get("zones") or {}).get("elements") or []
    rows: list[dict] = []
    for el in elements:
        if not el:
            continue
        zone = el.get("zone") or {}
        if not zone:
            continue
        if not include_hidden:
            if zone.get("visibility") is False:
                continue
            if zone.get("zoneState") == "zoneUnregistered":
                continue
        desc = el.get("description") or {}
        mode = el.get("mode") or {}
        flags = zone.get("flags") or {}
        # humidity == 0 means "no sensor" on TECH controllers, not 0% RH.
        raw_humidity = zone.get("humidity")
        humidity = None if raw_humidity in (None, 0) else raw_humidity
        rows.append(
            {
                "zone_id": zone.get("id"),
                "description_id": desc.get("id"),
                "mode_id": mode.get("id"),
                "name": desc.get("name"),
                "icon": desc.get("styleIcon"),
                "current_c": temp_from_api(zone.get("currentTemperature")),
                "set_c": temp_from_api(zone.get("setTemperature")),
                "humidity": humidity,
                "relay": flags.get("relayState"),
                "algorithm": flags.get("algorithm"),
                "action": _hvac_action(flags.get("relayState"), flags.get("algorithm")),
                "window_open": flags.get("minOneWindowOpen"),
                "battery": zone.get("batteryLevel"),
                "signal": zone.get("signalStrength"),
                "state": zone.get("zoneState"),
                "mode": mode.get("mode"),
                "mode_const_temp_c": temp_from_api(mode.get("setTemperature")),
                "mode_const_time_min": mode.get("constTempTime"),
                "schedule_index": mode.get("scheduleIndex"),
                "visibility": zone.get("visibility"),
                "during_change": zone.get("duringChange"),
                "updated_at": zone.get("time"),
            }
        )
    return rows


_ACTION_DISPLAY = {
    "heating": "[red]heating[/red]",
    "cooling": "[blue]cooling[/blue]",
    "idle": "[dim]idle[/dim]",
    "off": "[dim]off[/dim]",
}


def render_zones_table(rows: Iterable[dict], with_module_column: bool = False) -> None:
    table = Table(title="Zones", show_lines=False)
    cols = ["ID", "Name", "Cur °C", "Set °C", "Mode", "Action", "State", "Hum %"]
    if with_module_column:
        cols = ["Module"] + cols
    for col in cols:
        table.add_column(col)
    for r in rows:
        cells = [
            str(r.get("zone_id") or ""),
            str(r.get("name") or ""),
            f"{r.get('current_c'):.1f}" if r.get("current_c") is not None else "—",
            f"{r.get('set_c'):.1f}" if r.get("set_c") is not None else "—",
            str(r.get("mode") or ""),
            _ACTION_DISPLAY.get(r.get("action"), str(r.get("action") or "")),
            str(r.get("state") or ""),
            str(r.get("humidity")) if r.get("humidity") is not None else "—",
        ]
        if with_module_column:
            cells = [str(r.get("module_short") or r.get("module_name") or "")] + cells
        table.add_row(*cells)
    console.print(table)


def render_modules_table(modules: list[dict], active_udid: str | None = None) -> None:
    table = Table(title="Modules")
    table.add_column("Active")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("UDID")
    for m in modules:
        active = "*" if m.get("udid") == active_udid else ""
        table.add_row(
            active,
            str(m.get("name") or ""),
            str(m.get("type") or ""),
            str(m.get("version") or ""),
            str(m.get("moduleStatus") or ""),
            str(m.get("udid") or ""),
        )
    console.print(table)
