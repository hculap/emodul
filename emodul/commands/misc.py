"""Misc commands: tiles, i18n, poll, raw HTTP escape hatch."""
from __future__ import annotations

import json
import time

import click

from emodul import i18n as i18n_mod
from emodul.format import dump_json


def register(cli: click.Group, wrap) -> None:
    # ---------- tiles ----------
    @cli.group()
    def tiles() -> None:
        """Dashboard tiles (relays, sensors, fuel, version, etc.)."""

    @tiles.command("list")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--translate", is_flag=True, help="Resolve txtId via i18n cache.")
    @click.pass_obj
    @wrap
    def tiles_list(ctx, udid_arg: str | None, translate: bool) -> None:
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.get_tiles(udid)
            if translate:
                dictionary = i18n_mod.get_or_refresh(api, ctx.config.language)
                for el in data.get("elements", []) or []:
                    params = el.get("params") or {}
                    if "txtId" in params:
                        params["txtId_text"] = dictionary.get(str(params["txtId"]))
        dump_json(data)

    # ---------- i18n ----------
    @cli.group()
    def i18n() -> None:
        """Translation dictionary cache."""

    @i18n.command("refresh")
    @click.option("--language", default=None)
    @click.pass_obj
    @wrap
    def i18n_refresh(ctx, language: str | None) -> None:
        ctx.config.require_auth()
        lang = language or ctx.config.language
        with ctx.api() as api:
            d = i18n_mod.refresh_dictionary(api, lang)
        dump_json({"language": lang, "entries": len(d)})

    @i18n.command("lookup")
    @click.argument("txt_id", type=int)
    @click.option("--language", default=None)
    @click.pass_obj
    def i18n_lookup(ctx, txt_id: int, language: str | None) -> None:
        lang = language or ctx.config.language
        d = i18n_mod.load_dictionary(lang)
        if not d:
            raise SystemExit("No cached dictionary. Run `emodul i18n refresh` first.")
        dump_json({"txtId": txt_id, "text": d.get(str(txt_id))})

    # ---------- poll ----------
    @cli.command("poll")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--since",
        type=int,
        default=None,
        help="lastUpdate value from the previous poll (epoch seconds).",
    )
    @click.option(
        "--parents",
        default="[]",
        help="JSON array of unlocked menu nodes, e.g. '[\"MS:0:5162\"]'.",
    )
    @click.option("--alarm-ids", default="[]", help="JSON array of acknowledged alarm ids.")
    @click.pass_obj
    @wrap
    def poll(
        ctx,
        udid_arg: str | None,
        since: int | None,
        parents: str,
        alarm_ids: str,
    ) -> None:
        """Delta poll — what the SPA calls every 15 s for live updates."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        parents_l = json.loads(parents)
        alarm_l = json.loads(alarm_ids)
        with ctx.api() as api:
            data = api.update_data(
                udid, parents=parents_l, alarm_ids=alarm_l, last_update=since
            )
        dump_json(data)

    # ---------- raw escape hatch ----------
    @cli.command("raw")
    @click.argument("method")
    @click.argument("path")
    @click.option("--body", default=None, help="JSON body for POST/PUT.")
    @click.pass_obj
    @wrap
    def raw(ctx, method: str, path: str, body: str | None) -> None:
        """Issue an arbitrary API request. The AI agent's safety valve.

        The {user_id} placeholder is auto-substituted.
        """
        ctx.config.require_auth()
        if "{user_id}" in path and ctx.config.user_id:
            path = path.replace("{user_id}", str(ctx.config.user_id))
        if ctx.config.default_udid and "{udid}" in path:
            path = path.replace("{udid}", ctx.config.default_udid)
        body_obj = json.loads(body) if body else None
        method = method.upper()
        with ctx.api() as api:
            if method == "GET":
                data = api.get(path)
            elif method == "POST":
                data = api.post(path, body_obj)
            elif method == "PUT":
                data = api.put(path, body_obj)
            elif method == "DELETE":
                data = api.delete(path)
            elif method == "OPTIONS":
                data = api.options(path)
            else:
                raise click.BadParameter(f"unsupported method: {method}")
        if isinstance(data, str):
            click.echo(data)
        else:
            dump_json(data)

    # ---------- status (one-shot human snapshot) ----------
    @cli.command("status")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def status(ctx, udid_arg: str | None) -> None:
        """Compact human/AI overview: zone temps + active mode + last update."""
        from emodul.format import flatten_zones, render_zones_table

        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            snap = api.get_module(udid)
        rows = flatten_zones(snap)
        if ctx.json:
            dump_json(
                {
                    "udid": udid,
                    "fetched_at": int(time.time()),
                    "tiles_last_update": snap.get("tilesLastUpdate"),
                    "zones": rows,
                    "tile_count": len(snap.get("tiles") or []),
                }
            )
        else:
            render_zones_table(rows)
