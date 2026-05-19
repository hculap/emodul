"""`emodul zones ...` — read state, change setpoints, schedules, on/off, rename."""
from __future__ import annotations

import click

from emodul.format import (
    console,
    dump_json,
    flatten_zones,
    render_zones_table,
    temp_to_api,
)


def _settle_zone(api, udid: str, zone_id: int, wait: bool, timeout: float) -> bool:
    """Block until zone's duringChange flags clear, or timeout. Returns True if settled."""
    if not wait:
        return True
    return api.wait_until_settled(
        lambda: api.is_zone_settled(udid, zone_id), timeout=timeout
    )


def _zone_row(snapshot: dict, zone_id: int) -> dict | None:
    for row in flatten_zones(snapshot):
        if row.get("zone_id") == zone_id:
            return row
    return None


def _resolve_zone(snapshot: dict, query: str) -> dict | None:
    """Backwards-compatible wrapper; logic lives in _zone_resolver."""
    from emodul._zone_resolver import resolve_zone

    return resolve_zone(flatten_zones(snapshot), query)


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def zones() -> None:
        """Heating zones (thermostats)."""

    _register_audit(zones, wrap)

    @zones.command("list")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "-a",
        "--all-modules",
        "all_modules",
        is_flag=True,
        help="Iterate every module on the account. Adds Module column + module_name field.",
    )
    @click.pass_obj
    @wrap
    def list_(ctx, udid_arg: str | None, all_modules: bool) -> None:
        ctx.config.require_auth()
        with ctx.api() as api:
            if all_modules:
                modules = api.list_modules()
                targets = [
                    (m["udid"], m.get("name") or m["udid"][:8])
                    for m in modules
                    if m.get("udid")
                ]
            else:
                udid = ctx.resolve_module_udid(udid_arg)
                m_name = next(
                    (m.get("name") for m in api.list_modules() if m.get("udid") == udid),
                    udid[:8],
                )
                targets = [(udid, m_name)]
            rows: list[dict] = []
            for udid_, m_name in targets:
                snap = api.get_module(udid_)
                for r in flatten_zones(snap):
                    if all_modules:
                        # Short module label for tables; full name still in JSON
                        short = (m_name or "").split(",")[-1].strip()[:12]
                        r["module_udid"] = udid_
                        r["module_name"] = m_name
                        r["module_short"] = short
                    rows.append(r)
        if ctx.json:
            dump_json(rows)
        else:
            render_zones_table(rows, with_module_column=all_modules)

    @zones.command("show")
    @click.argument("zone")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def show(ctx, zone: str, udid_arg: str | None) -> None:
        """Show full data for one zone (id or name substring)."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
        row = _resolve_zone(snap, zone)
        if not row:
            raise SystemExit(f"Zone not found: {zone}")
        elements = (snap.get("zones") or {}).get("elements") or []
        raw = next(
            (
                el
                for el in elements
                if el and (el.get("zone") or {}).get("id") == row["zone_id"]
            ),
            None,
        )
        dump_json({"flat": row, "raw": raw})

    @zones.command("set-temp")
    @click.argument("zone")
    @click.argument("celsius", type=float)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--wait/--no-wait",
        default=True,
        show_default=True,
        help="Block until the zone's duringChange clears (~5-30s).",
    )
    @click.option("--timeout", type=float, default=30.0, show_default=True)
    @click.pass_obj
    @wrap
    def set_temp(
        ctx, zone: str, celsius: float, udid_arg: str | None, wait: bool, timeout: float
    ) -> None:
        """Set a zone to constantTemp at <celsius> (until manually changed)."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            row = _resolve_zone(snap, zone)
            if not row:
                raise SystemExit(f"Zone not found: {zone}")
            resp = api.set_zone_constant_temp(
                udid,
                mode_id=row["mode_id"],
                zone_id=row["zone_id"],
                set_temperature_int10=temp_to_api(celsius),
            )
            settled = _settle_zone(api, udid, row["zone_id"], wait, timeout)
        if ctx.json:
            dump_json(
                {
                    "ok": True,
                    "zone_id": row["zone_id"],
                    "set_c": celsius,
                    "settled": settled,
                    "response": resp,
                }
            )
        else:
            tag = "" if settled else "  [yellow](still applying)[/yellow]"
            console.print(f"[green]{row['name']}: setpoint → {celsius:.1f} °C[/green]{tag}")

    @zones.command("boost")
    @click.argument("zone")
    @click.argument("celsius", type=float)
    @click.argument("minutes", type=int)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--wait/--no-wait", default=True, show_default=True)
    @click.option("--timeout", type=float, default=30.0, show_default=True)
    @click.pass_obj
    @wrap
    def boost(
        ctx,
        zone: str,
        celsius: float,
        minutes: int,
        udid_arg: str | None,
        wait: bool,
        timeout: float,
    ) -> None:
        """Hold <celsius> for <minutes> (1-1440), then revert."""
        if not 1 <= minutes <= 1440:
            raise SystemExit("minutes must be 1..1440")
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            row = _resolve_zone(snap, zone)
            if not row:
                raise SystemExit(f"Zone not found: {zone}")
            resp = api.set_zone_time_limit(
                udid,
                mode_id=row["mode_id"],
                zone_id=row["zone_id"],
                set_temperature_int10=temp_to_api(celsius),
                minutes=minutes,
            )
            settled = _settle_zone(api, udid, row["zone_id"], wait, timeout)
        dump_json(
            {
                "ok": True,
                "zone_id": row["zone_id"],
                "minutes": minutes,
                "settled": settled,
                "response": resp,
            }
        )

    @zones.command("on")
    @click.argument("zone")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--wait/--no-wait", default=True, show_default=True)
    @click.option("--timeout", type=float, default=30.0, show_default=True)
    @click.pass_obj
    @wrap
    def on(ctx, zone: str, udid_arg: str | None, wait: bool, timeout: float) -> None:
        _toggle(ctx, zone, udid_arg, "zoneOn", wait, timeout)

    @zones.command("off")
    @click.argument("zone")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--wait/--no-wait", default=True, show_default=True)
    @click.option("--timeout", type=float, default=30.0, show_default=True)
    @click.pass_obj
    @wrap
    def off(ctx, zone: str, udid_arg: str | None, wait: bool, timeout: float) -> None:
        _toggle(ctx, zone, udid_arg, "zoneOff", wait, timeout)

    @zones.command("schedule")
    @click.argument("zone")
    @click.option(
        "--mode",
        "mode_kind",
        type=click.Choice(["local", "global"]),
        default="global",
        show_default=True,
    )
    @click.option(
        "--index",
        "schedule_index",
        type=int,
        default=0,
        show_default=True,
        help="globalSchedules slot (only for --mode global).",
    )
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def schedule(
        ctx, zone: str, mode_kind: str, schedule_index: int, udid_arg: str | None
    ) -> None:
        """Switch a zone to localSchedule / globalSchedule.

        For --mode global: reads the schedule definition from the controller
        and re-posts it with this zone added to `setInZones`. The naive
        POST /zones with `{mode: globalSchedule}` returns 422 — this is the
        endpoint that actually works.
        """
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            row = _resolve_zone(snap, zone)
            if not row:
                raise SystemExit(f"Zone not found: {zone}")
            if mode_kind == "global":
                gs = (snap.get("zones") or {}).get("globalSchedules") or {}
                elements = gs.get("elements") or []
                sched = next((s for s in elements if s.get("index") == schedule_index), None)
                if not sched:
                    raise SystemExit(
                        f"globalSchedule idx={schedule_index} not found. "
                        f"Available: {[s.get('index') for s in elements]}"
                    )
                resp = api.attach_global_schedule(
                    udid,
                    zone_id=row["zone_id"],
                    mode_id=row["mode_id"],
                    schedule_element=sched,
                )
            else:
                # local schedule — use the zone's existing schedule definition
                el = next(
                    (
                        e
                        for e in (snap.get("zones") or {}).get("elements") or []
                        if e and (e.get("zone") or {}).get("id") == row["zone_id"]
                    ),
                    None,
                )
                sched = (el or {}).get("schedule") or {}
                if not sched.get("id"):
                    raise SystemExit("Zone has no local schedule slot to activate.")
                # Filter placeholder intervals
                payload = dict(sched)
                payload["p0Intervals"] = [
                    i for i in (sched.get("p0Intervals") or []) if i.get("start", 9999) <= 1440
                ]
                payload["p1Intervals"] = [
                    i for i in (sched.get("p1Intervals") or []) if i.get("start", 9999) <= 1440
                ]
                resp = api.set_local_schedule(
                    udid,
                    zone_id=row["zone_id"],
                    mode_id=row["mode_id"],
                    schedule=payload,
                )
        dump_json({"ok": True, "response": resp})

    @zones.command("rename")
    @click.argument("zone")
    @click.argument("new_name")
    @click.option("--icon-id", type=int, default=0)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def rename(
        ctx, zone: str, new_name: str, icon_id: int, udid_arg: str | None
    ) -> None:
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            row = _resolve_zone(snap, zone)
            if not row:
                raise SystemExit(f"Zone not found: {zone}")
            resp = api.rename_zone(
                udid,
                zone_id=row["zone_id"],
                description_id=row["description_id"],
                name=new_name,
                icon_id=icon_id,
            )
        dump_json(resp)

    @zones.command("schedule-set")
    @click.argument("zone")
    @click.argument("schedule_json_file", type=click.Path(exists=True, dir_okay=False))
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def schedule_set(
        ctx, zone: str, schedule_json_file: str, udid_arg: str | None
    ) -> None:
        """Replace the zone's local weekly schedule with the JSON in <file>.

        File schema (matches the eModul schedule object):
          {"id": ..., "index": -1,
           "p0Days": ["1","1","1","1","1","0","0"],
           "p0Intervals": [{"start": 0, "stop": 360, "temp": 200}, ...],
           "p0SetbackTemp": 180,
           "p1Days": ["0","0","0","0","0","1","1"],
           "p1Intervals": [...],
           "p1SetbackTemp": 180}
        """
        import json

        with open(schedule_json_file, "r", encoding="utf-8") as f:
            schedule = json.load(f)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            row = _resolve_zone(snap, zone)
            if not row:
                raise SystemExit(f"Zone not found: {zone}")
            resp = api.set_local_schedule(
                udid, zone_id=row["zone_id"], mode_id=row["mode_id"], schedule=schedule
            )
        dump_json(resp)


def _register_audit(zones_group, wrap):
    """Behavioural audit — mean / min / max / stddev / setpoint-gap / gaps.

    Mirrors what we used to compute ad-hoc with Python + jq from the
    `stats linear` endpoint, plus an opinion column.
    """
    import datetime as dt
    import statistics as stats_mod

    @zones_group.command("audit")
    @click.option(
        "--period",
        type=click.Choice(["day", "week"]),
        default="week",
        show_default=True,
        help="Window of time-series to analyse (use `stats dump` for longer).",
    )
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def audit(ctx, period: str, udid_arg: str | None) -> None:
        """Compute behaviour metrics per zone (vs current setpoint)."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
            hist = api.stats_linear(udid, period=period)
        rows = flatten_zones(snap)
        setpoints = {r["name"]: r.get("set_c") for r in rows}
        modes = {r["name"]: r.get("mode") for r in rows}
        series = (hist.get("data") or {}).get("history") or {}
        out_rows = []
        for key, points in series.items():
            name = key.split("|")[-1]
            ys = [p["y"] for p in points if isinstance(p.get("y"), (int, float))]
            if not ys:
                continue
            xs = [_parse_ts(p["x"]) for p in points]
            xs = [x for x in xs if x]
            # Gaps > 5 min
            gaps = 0
            longest_gap = 0
            for i in range(1, len(xs)):
                delta = (xs[i] - xs[i - 1]).total_seconds() / 60
                if delta > 5:
                    gaps += 1
                    longest_gap = max(longest_gap, int(delta))
            sp = setpoints.get(name)
            mean = sum(ys) / len(ys)
            row = {
                "zone": name,
                "n": len(ys),
                "mean_c": round(mean, 2),
                "min_c": round(min(ys), 2),
                "max_c": round(max(ys), 2),
                "stdev_c": round(stats_mod.pstdev(ys), 2) if len(ys) > 1 else 0.0,
                "setpoint_c": sp,
                "gap_c": round(sp - mean, 2) if sp is not None else None,
                "pct_below_setpoint": (
                    round(100 * sum(1 for y in ys if sp is not None and y < sp) / len(ys), 1)
                    if sp is not None
                    else None
                ),
                "pct_above_setpoint_p5": (
                    round(100 * sum(1 for y in ys if sp is not None and y > sp + 0.5) / len(ys), 1)
                    if sp is not None
                    else None
                ),
                "gaps_5min": gaps,
                "longest_gap_min": longest_gap,
                "mode": modes.get(name),
                "verdict": _verdict(sp, mean, max(ys), stats_mod.pstdev(ys) if len(ys) > 1 else 0),
            }
            out_rows.append(row)
        if ctx.json:
            dump_json(
                {
                    "udid": udid,
                    "period": period,
                    "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "zones": out_rows,
                }
            )
            return
        from rich.table import Table

        table = Table(title=f"Zone audit — {period}", show_lines=False)
        for col in ("Zone", "N", "mean", "min", "max", "stdev", "set", "gap", "%<set", "%>set+0.5", "gaps", "longest", "verdict"):
            table.add_column(col)
        for r in out_rows:
            table.add_row(
                r["zone"],
                str(r["n"]),
                f"{r['mean_c']:.1f}",
                f"{r['min_c']:.1f}",
                f"{r['max_c']:.1f}",
                f"{r['stdev_c']:.2f}",
                f"{r['setpoint_c']}" if r["setpoint_c"] is not None else "—",
                f"{r['gap_c']:+.2f}" if r["gap_c"] is not None else "—",
                f"{r['pct_below_setpoint']}%" if r["pct_below_setpoint"] is not None else "—",
                f"{r['pct_above_setpoint_p5']}%" if r["pct_above_setpoint_p5"] is not None else "—",
                str(r["gaps_5min"]),
                f"{r['longest_gap_min']}m",
                r["verdict"],
            )
        console.print(table)


def _parse_ts(s: str):
    """eModul timestamp 'YYYYMMDDhhmm' → datetime."""
    import datetime as dt

    try:
        return dt.datetime.strptime(s, "%Y%m%d%H%M")
    except Exception:
        return None


def _verdict(sp: float | None, mean: float, peak: float, stdev: float) -> str:
    if sp is None:
        return "—"
    gap = sp - mean
    if gap > 1.0 and peak < sp:
        return "[red]nigdy nie osiąga setpointu[/red]"
    if gap > 0.5:
        return "[yellow]chronicznie poniżej[/yellow]"
    if stdev > 1.0:
        return "[yellow]szeroka oscylacja[/yellow]"
    if mean > sp + 0.3:
        return "[yellow]przegrzewa[/yellow]"
    return "[green]OK[/green]"


def _toggle(
    ctx, zone: str, udid_arg: str | None, state: str, wait: bool, timeout: float
) -> None:
    ctx.config.require_auth()
    udid = ctx.resolve_module_udid(udid_arg)
    with ctx.api() as api:
        snap = api.get_module(udid)
        row = _resolve_zone(snap, zone)
        if not row:
            raise SystemExit(f"Zone not found: {zone}")
        resp = api.set_zone_state(udid, zone_id=row["zone_id"], state=state)
        settled = _settle_zone(api, udid, row["zone_id"], wait, timeout)
    dump_json(
        {
            "ok": True,
            "zone_id": row["zone_id"],
            "new_state": state,
            "settled": settled,
            "response": resp,
        }
    )
