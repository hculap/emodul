"""`emodul modules ...` — list, select, show, sync, rename."""
from __future__ import annotations

import click

from emodul.format import console, dump_json, flatten_zones, render_modules_table


def _resolve_module(modules_list: list[dict], query: str) -> dict | None:
    """Match by exact udid first, then by case-insensitive name substring."""
    for m in modules_list:
        if m.get("udid") == query:
            return m
    q = query.lower()
    matches = [m for m in modules_list if q in (m.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]
    return None


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def modules() -> None:
        """Controllers attached to the account."""

    @modules.command("list")
    @click.pass_obj
    @wrap
    def list_(ctx) -> None:
        ctx.config.require_auth()
        with ctx.api() as api:
            data = api.list_modules()
        if ctx.json:
            dump_json(data)
        else:
            render_modules_table(data, active_udid=ctx.config.default_udid)

    @modules.command("select")
    @click.argument("query")
    @click.pass_obj
    @wrap
    def select(ctx, query: str) -> None:
        """Set the default module by udid or name substring."""
        ctx.config.require_auth()
        with ctx.api() as api:
            data = api.list_modules()
        match = _resolve_module(data, query)
        if not match:
            raise SystemExit(f"No unique module matches {query!r}.")
        udid = match["udid"]
        new_cfg = ctx.config.with_updates(default_udid=udid)
        new_cfg.save()
        ctx.config = new_cfg
        if ctx.json:
            dump_json({"selected": udid, "name": match.get("name")})
        else:
            console.print(f"[green]Default module → {match.get('name')} ({udid})[/green]")

    @modules.command("show")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--zones-only", is_flag=True, help="Show only the flattened zone list.")
    @click.pass_obj
    @wrap
    def show(ctx, udid_arg: str | None, zones_only: bool) -> None:
        """Fetch the full module snapshot (zones + tiles)."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.get_module(udid)
        if zones_only:
            data = flatten_zones(data)
        dump_json(data)

    @modules.command("sync")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def sync(ctx, udid_arg: str | None) -> None:
        """Trigger force_data_sync (rate-limited; 406 returns retry-after)."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.force_sync(udid)
        dump_json(data)

    @modules.command("rename")
    @click.argument("name")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--additional", default="", help="Free-text 'additional information' field.")
    @click.pass_obj
    @wrap
    def rename(ctx, name: str, udid_arg: str | None, additional: str) -> None:
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.update_module_info(udid, name=name, additional_information=additional)
        dump_json(data)
