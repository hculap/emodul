"""Read / audit / write named settings across every zone of a module.

Single implementation behind `emodul settings …` and the MCP settings tools.
"""
from __future__ import annotations

from typing import Any

from emodul._zone_settings import Target, ZoneRef, expand, present_in, zones_from_module
from emodul.api import ApiClient, EmodulApiError
from emodul.settings_map import Setting, find_item, find_value, is_accessible


def module_short(name: str) -> str:
    return (name or "").split(",")[-1].strip()


def gather_menus(
    api: ApiClient, cfg, udid: str, menu_types: set[str]
) -> tuple[dict[str, dict], dict[str, str]]:
    """Fetch each menu once with stored PINs. Returns (menus, errors by menu type)."""
    from emodul.commands.menu import _pin_chain

    menus: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for mt in sorted(menu_types):
        try:
            menus[mt] = api.get_menu(udid, mt, pin_chain=_pin_chain(cfg, udid, mt) or None)
        except EmodulApiError as exc:
            menus[mt] = {}
            errors[mt] = f"HTTP {exc.status}"
    return menus, errors


def targets_for(settings: list[Setting], zones: list[ZoneRef]) -> list[Target]:
    return [t for s in settings for t in expand(s, zones)]


def evaluate(targets: list[Target], menus: dict[str, dict]) -> list[dict[str, Any]]:
    """One row per target with current value and audit verdict."""
    rows = []
    for t in targets:
        s = t.setting
        menu = menus.get(s.menu_type, {})
        item = find_item(menu, t.ido)
        wire = find_value(menu, t.ido)
        severity, note = s.audit(wire)
        rows.append(
            {
                "name": s.name,
                "label": s.pl_label,
                "category": s.category,
                "menu": s.menu_type,
                "ido": t.ido,
                "zone": t.zone.name if t.zone else None,
                "zone_no": t.zone.no if t.zone else None,
                "wire": wire,
                "display": s.decode(wire),
                "present": item is not None,
                "accessible": is_accessible(item),
                "severity": severity,
                "audit_note": note,
            }
        )
    return rows


def read_module(
    api: ApiClient, cfg, udid: str, settings: list[Setting]
) -> tuple[list[ZoneRef], list[dict[str, Any]], dict[str, str]]:
    """Zones, evaluated rows and menu errors for one module."""
    zones = zones_from_module(api.get_module(udid))
    menus, errors = gather_menus(api, cfg, udid, {s.menu_type for s in settings})
    return zones, evaluate(targets_for(settings, zones), menus), errors


def findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bad/warn rows, skipping items the controller currently gates."""
    return [
        r
        for r in rows
        if r["severity"] in ("bad", "warn") and (r["accessible"] or not r["present"])
    ]


def drift(rows_by_module: dict[str, list[dict[str, Any]]], settings: list[Setting]) -> list[dict]:
    """Settings whose value differs where it should be uniform.

    Module-wide settings are compared across modules; zone-scoped ones across
    every zone of every module, except those whose zones legitimately differ
    (setpoints, presets, calibration).
    """
    out = []
    for s in settings:
        if s.per_zone_differs:
            continue
        values: dict[str, Any] = {}
        for module_name, rows in rows_by_module.items():
            for r in rows:
                if r["name"] != s.name or r["wire"] is None:
                    continue
                key = f"{module_short(module_name)} / {r['zone']}" if r["zone"] else module_name
                values[key] = r["wire"]
        if len(set(values.values())) > 1:
            field = "per_zone" if s.zone_scoped else "per_module"
            out.append(
                {
                    "name": s.name,
                    "label": s.pl_label,
                    field: {k: s.decode(v) for k, v in values.items()},
                }
            )
    return out


def write_targets(
    api: ApiClient,
    cfg,
    udid: str,
    targets: list[Target],
    wire: int,
    *,
    wait: bool,
    timeout: float,
) -> list[dict[str, Any]]:
    """Write `wire` to each target, one at a time; verify the value when waiting."""
    from emodul.commands.menu import _pin_chain

    results = []
    for t in targets:
        mt = t.setting.menu_type
        base = {"udid": udid, "zone": t.zone.name if t.zone else None, "ido": t.ido}
        try:
            resp = api.set_menu_param(udid, mt, t.ido, {"value": wire})
            verified = None
            if wait:
                chain = _pin_chain(cfg, udid, mt) or None
                verified = api.wait_until_settled(
                    lambda t=t, mt=mt, chain=chain: api.is_menu_item_at(
                        udid, mt, t.ido, wire, pin_chain=chain
                    ),
                    timeout=timeout,
                )
            results.append({**base, "ok": True, "verified": verified, "response": resp})
        except EmodulApiError as exc:
            results.append(
                {**base, "ok": False, "error": f"API {exc.status} on {exc.path}: {exc.body}"}
            )
    return results


def present_targets(
    api: ApiClient, cfg, udid: str, targets: list[Target]
) -> tuple[list[Target], list[Target]]:
    """Split targets into (exposed by this controller's menu, missing)."""
    menus, _ = gather_menus(api, cfg, udid, {t.setting.menu_type for t in targets})
    ok = [t for t in targets if present_in(t, menus)]
    return ok, [t for t in targets if t not in ok]
