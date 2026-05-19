"""`emodul settings ...` — high-level read/write of controller parameters.

Talks in friendly names ("emergency-mode") instead of raw IDOs. Also runs an
audit comparing observed values against known-bad defaults / recommendations.
"""
from __future__ import annotations

from collections import defaultdict

import click
from rich.table import Table

from emodul.commands.menu import _pin_chain
from emodul.format import console, dump_json, err_console
from emodul.settings_map import (
    SETTINGS,
    SETTINGS_BY_NAME,
    find_item,
    find_value,
    is_accessible,
)


def _gather_menu(api, cfg, udid: str) -> dict[str, dict]:
    """Fetch each unique menu_type once, auto-supplying stored PINs."""
    needed = sorted({s.menu_type for s in SETTINGS})
    out: dict[str, dict] = {}
    for mt in needed:
        chain = _pin_chain(cfg, udid, mt) or None
        try:
            out[mt] = api.get_menu(udid, mt, pin_chain=chain)
        except Exception as exc:
            err_console.print(
                f"[yellow]menu {mt} unavailable: {exc}[/yellow]"
                + ("  (try `emodul menu unlock MS 0 <pin>`)" if mt == "MS" else "")
            )
            out[mt] = {}
    return out


def _resolve_setting(name: str):
    s = SETTINGS_BY_NAME.get(name)
    if not s:
        names = ", ".join(sorted(SETTINGS_BY_NAME))
        raise click.BadParameter(f"unknown setting {name!r}.\nKnown: {names}")
    return s


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def settings() -> None:
        """High-level read/write of TECH controller parameters (no raw IDOs)."""

    @settings.command("list")
    def list_() -> None:
        """List every known setting name (machine-readable)."""
        dump_json(
            [
                {
                    "name": s.name,
                    "label": s.pl_label,
                    "menu": s.menu_type,
                    "ido": s.ido,
                    "kind": s.kind,
                    "category": s.category,
                    "note": s.note,
                }
                for s in SETTINGS
            ]
        )

    @settings.command("show")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--category",
        type=click.Choice(["actuator", "schedule", "safety", "diagnostic", "ux"]),
        default=None,
        help="Filter by category.",
    )
    @click.option(
        "--include-locked",
        is_flag=True,
        help="Show items the controller currently reports as locked (access=false).",
    )
    @click.pass_obj
    @wrap
    def show(
        ctx, udid_arg: str | None, category: str | None, include_locked: bool
    ) -> None:
        """Dashboard of all settings with current values + audit verdict."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            menus = _gather_menu(api, ctx.config, udid)
        items = [s for s in SETTINGS if not category or s.category == category]
        rows = []
        for s in items:
            item = find_item(menus.get(s.menu_type, {}), s.ido)
            accessible = is_accessible(item)
            if not include_locked and not accessible and item is not None:
                continue
            wire = find_value(menus.get(s.menu_type, {}), s.ido)
            severity, note = s.audit(wire)
            rows.append(
                {
                    "name": s.name,
                    "label": s.pl_label,
                    "category": s.category,
                    "menu": s.menu_type,
                    "ido": s.ido,
                    "wire": wire,
                    "display": s.decode(wire),
                    "accessible": accessible,
                    "severity": severity,
                    "audit_note": note,
                }
            )
        if ctx.json:
            dump_json({"udid": udid, "settings": rows})
            return
        table = Table(title=f"Settings — {udid[:8]}…", show_lines=False)
        for col in ("Name", "PL label", "Cat", "Value", "Verdict"):
            table.add_column(col)
        sev_style = {"ok": "green", "warn": "yellow", "bad": "red", "info": "dim"}
        for r in rows:
            style = sev_style.get(r["severity"], "")
            verdict = r["severity"].upper() + (f" — {r['audit_note']}" if r["audit_note"] else "")
            table.add_row(
                r["name"],
                r["label"],
                r["category"],
                r["display"],
                f"[{style}]{verdict}[/{style}]" if style else verdict,
            )
        console.print(table)

    @settings.command("get")
    @click.argument("name")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def get(ctx, name: str, udid_arg: str | None) -> None:
        """Read one setting by friendly name."""
        s = _resolve_setting(name)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            menu = api.get_menu(udid, s.menu_type)
        wire = find_value(menu, s.ido)
        severity, note = s.audit(wire)
        dump_json(
            {
                "name": s.name,
                "label": s.pl_label,
                "menu_type": s.menu_type,
                "ido": s.ido,
                "wire": wire,
                "display": s.decode(wire),
                "severity": severity,
                "audit_note": note,
            }
        )

    @settings.command("set")
    @click.argument("name")
    @click.argument("value")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--all-modules",
        is_flag=True,
        help="Apply to every module on the account (use carefully).",
    )
    @click.option(
        "--wait/--no-wait",
        default=True,
        show_default=True,
        help="Block until the controller clears its duringChange flag (~5-30s). "
        "Disable to return as soon as POST succeeds (may show stale value on re-read).",
    )
    @click.option(
        "--timeout",
        type=float,
        default=30.0,
        show_default=True,
        help="Max seconds to wait for settle.",
    )
    @click.pass_obj
    @wrap
    def set_(
        ctx,
        name: str,
        value: str,
        udid_arg: str | None,
        all_modules: bool,
        wait: bool,
        timeout: float,
    ) -> None:
        """Write one setting by friendly name. Value is in display units (°C, %, on/off)."""
        s = _resolve_setting(name)
        wire = s.encode(value)
        ctx.config.require_auth()
        with ctx.api() as api:
            if all_modules:
                targets = [m["udid"] for m in api.list_modules() if m.get("udid")]
            else:
                targets = [ctx.resolve_module_udid(udid_arg)]
            results = []
            for udid in targets:
                try:
                    resp = api.set_menu_param(udid, s.menu_type, s.ido, {"value": wire})
                    settled = True
                    if wait:
                        pin_chain = _pin_chain(ctx.config, udid, s.menu_type) or None
                        settled = api.wait_until_settled(
                            lambda u=udid: api.is_menu_item_settled(
                                u, s.menu_type, s.ido, pin_chain=pin_chain
                            ),
                            timeout=timeout,
                        )
                    results.append(
                        {"udid": udid, "ok": True, "settled": settled, "response": resp}
                    )
                except Exception as exc:
                    results.append({"udid": udid, "ok": False, "error": str(exc)})
        dump_json(
            {
                "name": s.name,
                "label": s.pl_label,
                "wire_value": wire,
                "display": s.decode(wire),
                "applied_to": results,
            }
        )

    @settings.command("audit")
    @click.option("-m", "--module", "udid_arg", default=None, help="One module; default: all.")
    @click.option(
        "--all-modules/--single",
        "all_modules",
        default=True,
        show_default=True,
        help="By default audit every module on the account.",
    )
    @click.pass_obj
    @wrap
    def audit(ctx, udid_arg: str | None, all_modules: bool) -> None:
        """Run heuristics on all settings; surface warnings + bad values per module."""
        ctx.config.require_auth()
        with ctx.api() as api:
            if all_modules and not udid_arg:
                modules = api.list_modules()
                targets = [(m["udid"], m.get("name") or m["udid"][:8]) for m in modules if m.get("udid")]
            else:
                udid = ctx.resolve_module_udid(udid_arg)
                name_for_udid = next(
                    (m.get("name") for m in api.list_modules() if m.get("udid") == udid),
                    udid[:8],
                )
                targets = [(udid, name_for_udid)]
            report: dict[str, dict] = {}
            for udid, label in targets:
                menus = _gather_menu(api, ctx.config, udid)
                findings: list[dict] = []
                for s in SETTINGS:
                    item = find_item(menus.get(s.menu_type, {}), s.ido)
                    # Skip items the controller has gated — they can't be
                    # changed right now anyway, so warning is just noise.
                    if not is_accessible(item) and item is not None:
                        continue
                    wire = find_value(menus.get(s.menu_type, {}), s.ido)
                    severity, note = s.audit(wire)
                    if severity in ("bad", "warn"):
                        findings.append(
                            {
                                "name": s.name,
                                "label": s.pl_label,
                                "current": s.decode(wire),
                                "wire": wire,
                                "severity": severity,
                                "note": note,
                                "fix": f"emodul settings set {s.name} <value> -m {udid[:8]}",
                            }
                        )
                report[label] = {
                    "udid": udid,
                    "issues": findings,
                    "counts": {
                        "bad": sum(1 for f in findings if f["severity"] == "bad"),
                        "warn": sum(1 for f in findings if f["severity"] == "warn"),
                    },
                }
        # Cross-module drift detection: same setting, different value
        all_known = defaultdict(dict)  # name -> {label_module: wire}
        with ctx.api() as api2:
            for udid, label in targets:
                menus = _gather_menu(api2, ctx.config, udid)
                for s in SETTINGS:
                    wire = find_value(menus.get(s.menu_type, {}), s.ido)
                    if wire is not None:
                        all_known[s.name][label] = wire
        drift = []
        if len(targets) > 1:
            for name, by_mod in all_known.items():
                vals = set(by_mod.values())
                if len(vals) > 1:
                    s = SETTINGS_BY_NAME[name]
                    drift.append(
                        {
                            "name": name,
                            "label": s.pl_label,
                            "per_module": {m: s.decode(v) for m, v in by_mod.items()},
                        }
                    )
        if ctx.json:
            dump_json({"per_module": report, "drift": drift})
            return
        for label, data in report.items():
            console.print(
                f"\n[bold]── {label}[/bold] "
                f"[red]{data['counts']['bad']} bad[/red] / "
                f"[yellow]{data['counts']['warn']} warn[/yellow]"
            )
            for f in data["issues"]:
                color = "red" if f["severity"] == "bad" else "yellow"
                console.print(
                    f"  [{color}]{f['severity'].upper()}[/{color}] {f['label']} "
                    f"= {f['current']}  — {f['note']}"
                )
                console.print(f"    fix: [dim]{f['fix']}[/dim]")
        if drift:
            console.print("\n[bold]── Config drift między sterownikami[/bold]")
            for d in drift:
                per = ", ".join(f"{m}={v}" for m, v in d["per_module"].items())
                console.print(f"  [magenta]{d['label']}[/magenta]: {per}")
