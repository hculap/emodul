"""Expand named settings into per-zone targets ("Strefa N").

Zone-scoped settings live at a different IDO per zone (see `settings_map`
strides). Shared by the CLI `settings` group and the MCP settings tools so
both read and write every zone, not just Strefa 1.
"""
from __future__ import annotations

from dataclasses import dataclass

from emodul.settings_map import Setting, find_item


@dataclass(frozen=True)
class ZoneRef:
    no: int      # 1-based "Strefa N" number (zone.index + 1)
    name: str


@dataclass(frozen=True)
class Target:
    setting: Setting
    zone: ZoneRef | None  # None for module-wide settings
    ido: int

    @property
    def label(self) -> str:
        return self.zone.name if self.zone else ""


def zones_from_module(module: dict) -> list[ZoneRef]:
    """Registered zones of a module snapshot, ordered by Strefa number."""
    zones: list[ZoneRef] = []
    for el in (module.get("zones") or {}).get("elements") or []:
        zone = (el or {}).get("zone") or {}
        index = zone.get("index")
        if index is None or zone.get("zoneState") == "zoneUnregistered":
            continue
        name = ((el or {}).get("description") or {}).get("name") or f"Strefa {index + 1}"
        zones.append(ZoneRef(no=index + 1, name=name))
    return sorted(zones, key=lambda z: z.no)


def select_zones(zones: list[ZoneRef], query: str) -> list[ZoneRef]:
    """Match a `--zone` value: digits → Strefa number, otherwise name substring.

    Raises ValueError when nothing or more than one zone matches.
    """
    if query.isdigit():
        matches = [z for z in zones if z.no == int(query)]
    else:
        q = query.lower()
        exact = [z for z in zones if z.name.lower() == q]
        matches = exact or [z for z in zones if q in z.name.lower()]
    if len(matches) != 1:
        known = ", ".join(f"{z.no}={z.name}" for z in zones)
        problem = "no zone" if not matches else "ambiguous zone"
        raise ValueError(f"{problem} {query!r}; zones: {known}")
    return matches


def expand(setting: Setting, zones: list[ZoneRef]) -> list[Target]:
    """One target for a module-wide setting, one per zone for a zone-scoped one."""
    if not setting.zone_scoped:
        return [Target(setting, None, setting.ido)]
    return [Target(setting, z, setting.ido_for(z.no)) for z in zones]


def present_in(target: Target, menus: dict[str, dict]) -> bool:
    """Whether the controller's menu actually exposes this target's IDO."""
    return find_item(menus.get(target.setting.menu_type, {}), target.ido) is not None
