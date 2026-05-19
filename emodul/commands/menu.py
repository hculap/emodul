"""`emodul menu ...` — browse and write all four menu trees (MU/MI/MS/MP).

PIN handling: unlocked PINs are persisted in config.pins so subsequent calls
include them automatically as the parent chain. To unlock the service menu
with PIN 5162: `emodul menu unlock MS 0 5162`.
"""
from __future__ import annotations

import json

import click

from emodul.format import dump_json

MENU_TYPES = {
    "menu": "MU",
    "user": "MU",
    "MU": "MU",
    "fitters": "MI",
    "MI": "MI",
    "service": "MS",
    "MS": "MS",
    "manufacturer": "MP",
    "MP": "MP",
}


def _normalize_menu(t: str) -> str:
    if t not in MENU_TYPES:
        raise click.BadParameter(
            "menu type must be one of: MU MI MS MP (or aliases: user/fitters/service/manufacturer)"
        )
    return MENU_TYPES[t]


def _pin_chain(cfg, udid: str, menu_type: str) -> list[tuple[int, str]]:
    stored = (cfg.pins.get(udid) or {}).get(menu_type) or {}
    # `0:<pin>` (root) first, then deeper ids in numeric order.
    items: list[tuple[int, str]] = []
    if "0" in stored:
        items.append((0, stored["0"]))
    for k in sorted((int(x) for x in stored.keys() if x != "0")):
        items.append((k, stored[str(k)]))
    return items


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def menu() -> None:
        """User / fitters / service / manufacturer menu trees."""

    @menu.command("show")
    @click.argument("menu_type")
    @click.argument("subpath", nargs=-1)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def show(ctx, menu_type: str, subpath: tuple[str, ...], udid_arg: str | None) -> None:
        """Fetch a menu page.

        Examples:
          emodul menu show MU
          emodul menu show MS                          # uses saved root PIN
          emodul menu show MS 12:5162 47:5162          # explicit chain
        """
        mt = _normalize_menu(menu_type)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        chain: list[tuple[int, str]]
        if subpath:
            chain = []
            for token in subpath:
                if ":" not in token:
                    raise click.BadParameter(f"expected ID:PIN, got {token!r}")
                i, p = token.split(":", 1)
                chain.append((int(i), p))
        else:
            chain = _pin_chain(ctx.config, udid, mt)
        with ctx.api() as api:
            data = api.get_menu(udid, mt, pin_chain=chain or None)
        dump_json(data)

    @menu.command("unlock")
    @click.argument("menu_type")
    @click.argument("node_id", type=int)
    @click.argument("pin")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def unlock(ctx, menu_type: str, node_id: int, pin: str, udid_arg: str | None) -> None:
        """Save a PIN for (menu_type, node_id) and verify it by fetching the menu."""
        mt = _normalize_menu(menu_type)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        pins = json.loads(json.dumps(ctx.config.pins))  # deep copy via JSON
        pins.setdefault(udid, {}).setdefault(mt, {})[str(node_id)] = pin
        new_cfg = ctx.config.with_updates(pins=pins)
        with ctx.api() as api:
            chain = _pin_chain(new_cfg, udid, mt)
            data = api.get_menu(udid, mt, pin_chain=chain)
        new_cfg.save()
        ctx.config = new_cfg
        dump_json({"ok": True, "stored_pin_for": [udid, mt, node_id], "menu": data})

    @menu.command("forget-pins")
    @click.argument("menu_type", required=False)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    def forget(ctx, menu_type: str | None, udid_arg: str | None) -> None:
        """Wipe stored PINs (for one menu type, one module, or everything)."""
        pins = json.loads(json.dumps(ctx.config.pins))
        if udid_arg and menu_type:
            mt = _normalize_menu(menu_type)
            pins.get(udid_arg, {}).pop(mt, None)
        elif udid_arg:
            pins.pop(udid_arg, None)
        else:
            pins = {}
        new_cfg = ctx.config.with_updates(pins=pins)
        new_cfg.save()
        dump_json({"ok": True, "remaining": pins})

    @menu.command("set")
    @click.argument("menu_type")
    @click.argument("ido", type=int)
    @click.argument("value")
    @click.option(
        "--raw",
        is_flag=True,
        help="Treat <value> as a raw JSON object to send as the request body.",
    )
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def set_(ctx, menu_type: str, ido: int, value: str, raw: bool, udid_arg: str | None) -> None:
        """Write a menu parameter.

        Examples:
          emodul menu set MU 1234 21                 # → {"value": 21}
          emodul menu set MS 5566 --raw '{"value":1,"type":20}'
        """
        mt = _normalize_menu(menu_type)
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        if raw:
            body = json.loads(value)
        else:
            try:
                body = {"value": int(value)}
            except ValueError:
                body = {"value": value}
        with ctx.api() as api:
            data = api.set_menu_param(udid, mt, ido, body)
        dump_json(data)
