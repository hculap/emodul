"""`emodul settings ...` — high-level read/write of controller parameters.

Talks in friendly names ("emergency-mode") instead of raw IDOs. Zone-scoped
settings are read and written per zone ("Strefa N"); module-wide ones once.
Also runs an audit comparing observed values against known-bad defaults.
"""
from __future__ import annotations

import click
from rich.table import Table

from emodul import _settings_ops as ops
from emodul._zone_settings import expand, select_zones, zones_from_module
from emodul.format import console, dump_json
from emodul.settings_map import SETTINGS, SETTINGS_BY_NAME


def _resolve_setting(name: str):
    s = SETTINGS_BY_NAME.get(name)
    if not s:
        names = ", ".join(sorted(SETTINGS_BY_NAME))
        raise click.BadParameter(f"unknown setting {name!r}.\nKnown: {names}")
    return s


def _filter_zone(rows: list[dict], zones, zone_query: str | None) -> list[dict]:
    if not zone_query:
        return rows
    try:
        wanted = {z.name for z in select_zones(zones, zone_query)}
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--zone") from exc
    return [r for r in rows if r["zone"] is None or r["zone"] in wanted]


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
                    "scope": "zone" if s.zone_scoped else "module",
                    "kind": s.kind,
                    "category": s.category,
                    "note": s.note,
                }
                for s in SETTINGS
            ]
        )

    @settings.command("show")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--zone", "zone_query", default=None, help="Only this zone (name or Strefa number).")
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
        ctx,
        udid_arg: str | None,
        zone_query: str | None,
        category: str | None,
        include_locked: bool,
    ) -> None:
        """Dashboard of all settings, per zone, with current values + audit verdict."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        items = [s for s in SETTINGS if not category or s.category == category]
        with ctx.api() as api:
            zones, rows, errors = ops.read_module(api, ctx.config, udid, items)
        rows = _filter_zone(rows, zones, zone_query)
        if not include_locked:
            rows = [r for r in rows if r["accessible"] or not r["present"]]
        if ctx.json:
            dump_json(
                {
                    "udid": udid,
                    "zones": [{"no": z.no, "name": z.name} for z in zones],
                    "settings": rows,
                    "menu_errors": errors,
                }
            )
            return
        table = Table(title=f"Settings — {udid[:8]}…", show_lines=False)
        for col in ("Name", "Zone", "PL label", "Value", "Verdict"):
            table.add_column(col)
        sev_style = {"ok": "green", "warn": "yellow", "bad": "red", "info": "dim"}
        for r in rows:
            style = sev_style.get(r["severity"], "")
            verdict = r["severity"].upper() + (f" — {r['audit_note']}" if r["audit_note"] else "")
            zone = f"{r['zone_no']} {r['zone']}" if r["zone"] else "—"
            table.add_row(
                r["name"],
                zone,
                r["label"],
                r["display"],
                f"[{style}]{verdict}[/{style}]" if style else verdict,
            )
        console.print(table)
        for mt, err in errors.items():
            console.print(f"[yellow]menu {mt} unavailable: {err}[/yellow]")

    @settings.command("get")
    @click.argument("name")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--zone", "zone_query", default=None, help="Only this zone (name or Strefa number).")
    @click.pass_obj
    @wrap
    def get(ctx, name: str, udid_arg: str | None, zone_query: str | None) -> None:
        """Read one setting by friendly name (every zone for zone-scoped settings)."""
        s = _resolve_setting(name)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            zones, rows, errors = ops.read_module(api, ctx.config, udid, [s])
        rows = _filter_zone(rows, zones, zone_query)
        head = {"name": s.name, "label": s.pl_label, "menu_type": s.menu_type}
        if not s.zone_scoped:
            r = rows[0]
            dump_json(
                {
                    **head,
                    "scope": "module",
                    "ido": r["ido"],
                    "wire": r["wire"],
                    "display": r["display"],
                    "severity": r["severity"],
                    "audit_note": r["audit_note"],
                    "menu_errors": errors,
                }
            )
            return
        keys = ("zone", "zone_no", "ido", "wire", "display", "present", "severity", "audit_note")
        dump_json(
            {
                **head,
                "scope": "zone",
                "zones": [{k: r[k] for k in keys} for r in rows],
                "menu_errors": errors,
            }
        )

    @settings.command("set")
    @click.argument("name")
    @click.argument("value")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--zone",
        "zone_query",
        default=None,
        help="Zone-scoped settings: target zone (name or Strefa number).",
    )
    @click.option(
        "--all-zones",
        is_flag=True,
        help="Zone-scoped settings: write every zone of the module.",
    )
    @click.option(
        "--all-modules",
        is_flag=True,
        help="Apply to every module on the account (use carefully).",
    )
    @click.option(
        "--wait/--no-wait",
        default=True,
        show_default=True,
        help="Block until the controller reports the new value (~5-30s per write). "
        "Disable to return as soon as POST succeeds (may show stale value on re-read).",
    )
    @click.option(
        "--timeout",
        type=float,
        default=60.0,
        show_default=True,
        help="Max seconds to wait for each write to settle.",
    )
    @click.pass_obj
    @wrap
    def set_(
        ctx,
        name: str,
        value: str,
        udid_arg: str | None,
        zone_query: str | None,
        all_zones: bool,
        all_modules: bool,
        wait: bool,
        timeout: float,
    ) -> None:
        """Write one setting by friendly name. Value is in display units (°C, %, on/off).

        Zone-scoped settings (emergency-mode, hysteresis, sigma-range, …) need
        --zone <name|number> or --all-zones; `settings list` shows each scope.
        """
        s = _resolve_setting(name)
        if s.zone_scoped and not (zone_query or all_zones):
            raise click.UsageError(
                f"{s.name} is set per zone; pass --zone <name|number> or --all-zones."
            )
        if s.zone_scoped and zone_query and all_zones:
            raise click.UsageError("use either --zone or --all-zones, not both.")
        if not s.zone_scoped and (zone_query or all_zones):
            raise click.UsageError(f"{s.name} is module-wide; drop --zone/--all-zones.")
        wire = s.encode(value)
        ctx.config.require_auth()
        results = []
        with ctx.api() as api:
            if all_modules:
                udids = [m["udid"] for m in api.list_modules() if m.get("udid")]
            else:
                udids = [ctx.resolve_module_udid(udid_arg)]
            for udid in udids:
                zones = zones_from_module(api.get_module(udid))
                try:
                    chosen = select_zones(zones, zone_query) if zone_query else zones
                except ValueError as exc:
                    results.append({"udid": udid, "ok": False, "error": str(exc)})
                    continue
                present, missing = ops.present_targets(
                    api, ctx.config, udid, expand(s, chosen)
                )
                results += [
                    {
                        "udid": udid,
                        "zone": t.zone.name if t.zone else None,
                        "ido": t.ido,
                        "ok": False,
                        "error": "not in this controller's menu",
                    }
                    for t in missing
                ]
                results += ops.write_targets(
                    api, ctx.config, udid, present, wire, wait=wait, timeout=timeout
                )
        dump_json(
            {
                "name": s.name,
                "label": s.pl_label,
                "wire_value": wire,
                "display": s.decode(wire),
                "applied_to": results,
            }
        )
        if any(not r["ok"] or r.get("verified") is False for r in results):
            raise SystemExit(1)

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
        """Run heuristics on all settings of every zone; surface bad/warn values and drift."""
        ctx.config.require_auth()
        with ctx.api() as api:
            modules = api.list_modules()
            if all_modules and not udid_arg:
                targets = [(m["udid"], m.get("name") or m["udid"][:8]) for m in modules if m.get("udid")]
            else:
                udid = ctx.resolve_module_udid(udid_arg)
                label = next((m.get("name") for m in modules if m.get("udid") == udid), udid[:8])
                targets = [(udid, label)]
            report: dict[str, dict] = {}
            rows_by_module: dict[str, list[dict]] = {}
            for udid, label in targets:
                _, rows, errors = ops.read_module(api, ctx.config, udid, SETTINGS)
                rows_by_module[label] = rows
                issues = [
                    {
                        "name": r["name"],
                        "label": r["label"],
                        "zone": r["zone"],
                        "zone_no": r["zone_no"],
                        "current": r["display"],
                        "wire": r["wire"],
                        "severity": r["severity"],
                        "note": r["audit_note"],
                        "fix": f"emodul settings set {r['name']} <value> -m {udid[:8]}"
                        + (f" --zone {r['zone_no']}" if r["zone_no"] else ""),
                    }
                    for r in ops.findings(rows)
                ]
                report[label] = {
                    "udid": udid,
                    "issues": issues,
                    "counts": {
                        "bad": sum(1 for f in issues if f["severity"] == "bad"),
                        "warn": sum(1 for f in issues if f["severity"] == "warn"),
                    },
                    "menu_errors": errors,
                }
        drift = ops.drift(rows_by_module, SETTINGS)
        if ctx.json:
            dump_json({"per_module": report, "drift": drift})
            return
        for label, data in report.items():
            console.print(
                f"\n[bold]── {label}[/bold] "
                f"[red]{data['counts']['bad']} bad[/red] / "
                f"[yellow]{data['counts']['warn']} warn[/yellow]"
            )
            for mt, err in data["menu_errors"].items():
                console.print(f"  [yellow]menu {mt} unavailable: {err}[/yellow]")
            for f in data["issues"]:
                color = "red" if f["severity"] == "bad" else "yellow"
                where = f" [{f['zone']}]" if f["zone"] else ""
                console.print(
                    f"  [{color}]{f['severity'].upper()}[/{color}] {f['label']}{where} "
                    f"= {f['current']}  — {f['note']}"
                )
                console.print(f"    fix: [dim]{f['fix']}[/dim]")
        if drift:
            console.print("\n[bold]── Config drift[/bold]")
            for d in drift:
                values = d.get("per_zone") or d.get("per_module") or {}
                per = ", ".join(f"{k}={v}" for k, v in values.items())
                console.print(f"  [magenta]{d['label']}[/magenta]: {per}")
