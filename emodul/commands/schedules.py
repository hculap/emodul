"""`emodul schedules ...` — readable view of the controller's globalSchedules.

Each TECH controller has exactly 5 globalSchedules slots (idx 0-4). The CLI
shows day masks (Mon-Sun), heating intervals (decoded from minutes-of-day +
tenths-of-°C), the setback temperature, and which zones currently reference
each schedule.
"""
from __future__ import annotations

import click
from rich.table import Table

from emodul._schedule_format import decode_schedule as _decode_schedule
from emodul._schedule_format import zones_using_schedule as _zones_using
from emodul.format import console, dump_json


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def schedules() -> None:
        """Browse globalSchedules of the controller."""

    @schedules.command("list")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def list_(ctx, udid_arg: str | None) -> None:
        """Show all 5 globalSchedules with decoded times and active zones."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
        gs = (snap.get("zones") or {}).get("globalSchedules", {}).get("elements") or []
        rows = []
        for s in sorted(gs, key=lambda x: x.get("index", 0)):
            dec = _decode_schedule(s)
            dec["used_by"] = _zones_using(snap, dec["index"])
            rows.append(dec)
        if ctx.json:
            dump_json(rows)
            return
        table = Table(title="Global schedules", show_lines=True)
        for col in ("Idx", "Name", "Dni", "Interwały (temp)", "Setback", "Używają"):
            table.add_column(col)
        for r in rows:
            inter = "\n".join(
                f"{i['start']}-{i['stop']} → {i['temp_c']:.1f} °C"
                for i in r["p0_intervals"]
            ) or "[dim](pusty)[/dim]"
            used = ", ".join(r["used_by"]) if r["used_by"] else "[dim](nieużywany)[/dim]"
            table.add_row(
                str(r["index"]),
                r["name"],
                r["p0_days"],
                inter,
                f"{r['p0_setback_c']:.1f} °C",
                used,
            )
        console.print(table)

    @schedules.command("show")
    @click.argument("query")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def show(ctx, query: str, udid_arg: str | None) -> None:
        """Show one schedule by index (0-4) or name substring."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
        gs = (snap.get("zones") or {}).get("globalSchedules", {}).get("elements") or []
        match = None
        if query.isdigit():
            idx = int(query)
            match = next((s for s in gs if s.get("index") == idx), None)
        if match is None:
            q = query.lower()
            cands = [s for s in gs if q in (s.get("name") or "").lower()]
            if len(cands) == 1:
                match = cands[0]
        if match is None:
            raise SystemExit(f"Schedule not found: {query}")
        out = _decode_schedule(match)
        out["used_by"] = _zones_using(snap, out["index"])
        out["raw_p0Days"] = match.get("p0Days")
        out["raw_p1Days"] = match.get("p1Days")
        dump_json(out)
