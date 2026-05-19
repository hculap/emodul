"""emodul MCP server.

Exposes ~15 tools so chat-based AI agents can drive the heating system.

Architecture:
- FastMCP (`mcp.server.fastmcp.FastMCP`) — Anthropic-canonical SDK pattern
- Sync `ApiClient` calls bridged into async tools via `anyio.to_thread.run_sync`
- Tools return JSON-safe dicts; errors come back as `{ok: false, error, code}`
  envelopes rather than raised exceptions (raising kills the server)
- Writes use `ToolAnnotations(destructiveHint=True)` so well-behaved clients
  render a confirmation prompt before invocation

Entry point: `python -m emodul.mcp.server` or `emodul mcp` (Click subcommand).
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from emodul._zone_resolver import resolve_zone as _resolve_zone_helper
from emodul.api import EmodulApiError
from emodul.format import flatten_zones, temp_to_api
from emodul.mcp._helpers import (
    err_response,
    ok_response,
    open_api,
    resolve_udid,
    safely,
)
from emodul.settings_map import (
    SETTINGS,
    SETTINGS_BY_NAME,
    find_item,
    find_value,
    is_accessible,
)

# Logging to stderr — stdio MCP transport reserves stdout for JSON-RPC.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("emodul.mcp")

mcp = FastMCP(
    "emodul",
    instructions="""\
Control a Polish Tech Sterowniki / eModul.pl floor-heating system (TECH \
controllers L-4X / L-8 / L-9 / L-12) via 16 MCP tools.

WHEN TO USE: any request mentioning heating, room temperature, floor heating, \
ogrzewanie, a room thermostat (typical Polish zone names: Salon, Łazienka, \
Sypialnia, Pokój, Biuro, Garaż, Kuchnia), boiler, eModul cloud, weekly heating \
schedules, serwis menu / PIN, alarm history, historical temperature data. \
Polish trigger phrases: "ustaw temperaturę", "podgrzej", "włącz/wyłącz \
ogrzewanie", "ile stopni", "harmonogram grzania".

TOOLS (16):
- READ (safe): whoami, list_modules, get_status, list_zones, get_zone, \
list_schedules, audit_settings, get_alarms, get_temperature_history
- WRITE (destructiveHint=true, client prompts for confirmation): \
set_zone_temperature, boost_zone, toggle_zone, attach_schedule, update_setting
- AUTH: login_browser, set_default_module

WORKFLOW:
1. whoami → if token_present=false, call login_browser (opens local form, the \
password never reaches you; returns once user submits or after timeout).
2. list_modules → discover controllers. Users name them freely (one per floor, \
per building, anything). NEVER hard-code module names — always discover first.
3. Optionally set_default_module once, then subsequent calls omit `module`.
4. For zone requests: list_zones first to enumerate, then act.

CONVENTIONS:
- Temperatures: Celsius, 0.1° precision (e.g. 21.5). Wire encoding handled.
- Zone selectors: case-insensitive name substring OR numeric id.
- Modes (zone.mode.mode): constantTemp / timeLimit (boost) / localSchedule / \
globalSchedule (5 shared slots indexed 0-4).
- Action field: heating / cooling / idle / off.
- Schedule intervals: minutes-of-day (0-1439).

RESULT ENVELOPE: every tool returns {ok: true, ...payload} or {ok: false, \
error, code}. Codes: auth_required, login_failed, api_error (with status), \
not_found, bad_input, internal. CHECK `ok` BEFORE CHAINING WRITES.

SAFETY:
- Writes block 5-30s while the controller acknowledges — do not time out the \
call early.
- Narrate writes before invoking ("I'm going to set Salon to 21.5 °C"); the \
destructiveHint prompt is not a substitute for transparency.
- NEVER log or echo JWT, password, user_id, controller udid, email, or the \
service-menu PIN (typically 5162 on TECH controllers).
- In summer (May-Sep) the furnace is often off, so zones sit below setpoint \
and per-zone relays read "off" even though the system "works" — do not \
diagnose hardware faults from temperature data alone in off-season; ask the \
user.
- Long get_temperature_history calls risk the client's ~60s tool timeout — \
narrow the date range and chunk if needed.
""",
)


# ---------------------------------------------------------------- READ tools


@mcp.tool()
@safely
async def whoami() -> dict:
    """Return authentication state + default module. Always safe to call.

    Returns a dict with `authenticated`, `email`, `user_id`, `default_udid`,
    `default_module_name` (if cached). If `authenticated` is false, call
    `login_browser` to interactively authenticate.
    """

    def _impl() -> dict:
        from emodul.config import Config

        cfg = Config.load()
        out: dict[str, Any] = {
            "authenticated": bool(cfg.token and cfg.user_id),
            "email": cfg.email,
            "user_id": cfg.user_id,
            "default_udid": cfg.default_udid,
            "base_url": cfg.base_url,
            "language": cfg.language,
        }
        if out["authenticated"]:
            try:
                with open_api(require_auth=True) as (api, _):
                    info = api.user_info()
                    out["server_info"] = {
                        "accountEmail": info.get("accountEmail"),
                        "firstName": info.get("firstName"),
                        "lastName": info.get("lastName"),
                    }
            except EmodulApiError as exc:
                # 401/403 → the cached token is dead. Flip authenticated so
                # the agent calls `login_browser` instead of proceeding.
                if exc.status in (401, 403):
                    out["authenticated"] = False
                    out["refresh_required"] = True
                out["server_info_error"] = {
                    "kind": "api",
                    "status": exc.status,
                    "message": str(exc.body) if exc.body else f"HTTP {exc.status}",
                }
            except Exception as exc:  # noqa: BLE001
                out["server_info_error"] = {"kind": "internal", "message": str(exc)}
        return ok_response(**out)

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def get_status(module: str | None = None) -> dict:
    """Snapshot of all zones in one module (kitchen-sink read).

    Args:
        module: Optional module name / udid / prefix. Default: the user's
                default module (set via CLI `emodul modules select`).

    Returns: `{ok, udid, fetched_at, zones: [...], tile_count}`.
    Each zone has `zone_id`, `name`, `current_c`, `set_c`, `mode`, `action`
    (heating/idle/off/cooling), `state`, `humidity`, `relay`, etc.

    Use this when the user asks "what's the temperature in X?", "is the
    heating running?", "show me the state".
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
        return ok_response(
            udid=udid,
            fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            tiles_last_update=snap.get("tilesLastUpdate"),
            zones=flatten_zones(snap),
            tile_count=len(snap.get("tiles") or []),
        )

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def list_zones(all_modules: bool = False, module: str | None = None) -> dict:
    """List all heating zones, optionally across all controllers.

    Args:
        all_modules: If true, return zones from every controller on the
                     account (each row gets `module_short` + `module_name`).
        module: When `all_modules=False`, which single module to query.

    Returns: `{ok, zones: [...]}` flattened. Useful for "list all zones in
    my house" or "show heating across the whole building".
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            if all_modules:
                mods = api.list_modules()
                targets = [
                    (m["udid"], m.get("name") or m["udid"][:8])
                    for m in mods
                    if m.get("udid")
                ]
            else:
                udid = resolve_udid(module, api, cfg)
                name = next(
                    (m.get("name") for m in api.list_modules() if m.get("udid") == udid),
                    udid[:8],
                )
                targets = [(udid, name)]
            rows: list[dict] = []
            for udid_, m_name in targets:
                snap = api.get_module(udid_)
                for r in flatten_zones(snap):
                    if all_modules:
                        r["module_udid"] = udid_
                        r["module_name"] = m_name
                        r["module_short"] = (m_name or "").split(",")[-1].strip()[:12]
                    rows.append(r)
        return ok_response(zones=rows, count=len(rows))

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def get_zone(zone: str, module: str | None = None) -> dict:
    """Detailed state of a single zone by name (substring) or numeric ID.

    Args:
        zone: Zone name (case-insensitive substring) or numeric `zone_id`.
        module: Optional module override.

    Returns: `{ok, flat: {...}, raw: {...}}`. `flat` is the simplified shape
    from `list_zones`; `raw` is the full API object including schedule and
    actuator details. Use `raw.schedule` to inspect the per-zone schedule
    definition.
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
        match = _resolve_zone_helper(flatten_zones(snap), zone)
        if not match:
            raise LookupError(f"Zone not found or ambiguous: {zone}")
        elements = (snap.get("zones") or {}).get("elements") or []
        raw = next(
            (
                el
                for el in elements
                if el and (el.get("zone") or {}).get("id") == match["zone_id"]
            ),
            None,
        )
        return ok_response(flat=match, raw=raw)

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def list_modules() -> dict:
    """List all heating controllers on the user's eModul account.

    Returns: `{ok, modules: [...]}` where each has `udid`, `name`, `version`
    (controller firmware), `moduleStatus`, etc. Use the resulting `udid` (or
    `name`) as the `module` argument in other tools.
    """

    def _impl() -> dict:
        with open_api() as (api, _):
            mods = api.list_modules()
        return ok_response(modules=mods, count=len(mods))

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def list_schedules(module: str | None = None) -> dict:
    """List all 5 globalSchedule slots of a controller (decoded).

    Each schedule has day mask (`Pn Wt Śr Cz Pt — —`), `p0_intervals`
    (start/stop times in HH:MM + temp in °C), setback temperature, and
    which zones currently reference it (`used_by`).

    Returns: `{ok, schedules: [...]}`.
    """
    from emodul._schedule_format import decode_schedule, zones_using_schedule

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
        gs = (snap.get("zones") or {}).get("globalSchedules", {}).get("elements") or []
        out = []
        for s in sorted(gs, key=lambda x: x.get("index", 0)):
            dec = decode_schedule(s)
            dec["used_by"] = zones_using_schedule(snap, dec["index"])
            out.append(dec)
        return ok_response(schedules=out)

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def audit_settings() -> dict:
    """Audit configuration of every controller; flag bad/non-default values.

    Walks all 25 known settings (emergency-mode, hysteresis, sigma-range,
    antifreeze, etc.) on each module. Returns per-module findings + a
    `drift` section showing parameters that differ between controllers
    (typically a sign of accidental config divergence).

    Read-only. Always safe to call.

    Returns: `{ok, per_module: {...}, drift: [...]}`.
    """

    def _impl() -> dict:
        from emodul.commands.menu import _pin_chain

        with open_api() as (api, cfg):
            mods = api.list_modules()
            targets = [
                (m["udid"], m.get("name") or m["udid"][:8])
                for m in mods
                if m.get("udid")
            ]
            report: dict[str, dict] = {}
            all_known: dict[str, dict] = {}
            menus_by_module: dict[str, dict] = {}
            needed = sorted({s.menu_type for s in SETTINGS})
            menu_errors_by_module: dict[str, dict[str, str]] = {}
            for udid, label in targets:
                menus: dict = {}
                menu_errors: dict[str, str] = {}
                for mt in needed:
                    chain = _pin_chain(cfg, udid, mt) or None
                    try:
                        menus[mt] = api.get_menu(udid, mt, pin_chain=chain)
                    except EmodulApiError as exc:
                        # Record but continue — partial audits are still useful.
                        # Surface the failure so the user knows the report
                        # is incomplete (e.g. MS PIN missing → 403).
                        menus[mt] = {}
                        menu_errors[mt] = f"HTTP {exc.status}"
                menus_by_module[udid] = menus
                menu_errors_by_module[udid] = menu_errors
                findings = []
                for s in SETTINGS:
                    item = find_item(menus.get(s.menu_type, {}), s.ido)
                    if not is_accessible(item) and item is not None:
                        continue
                    wire = find_value(menus.get(s.menu_type, {}), s.ido)
                    if wire is not None:
                        all_known.setdefault(s.name, {})[label] = wire
                    severity, note = s.audit(wire)
                    if severity in ("bad", "warn"):
                        findings.append(
                            {
                                "name": s.name,
                                "label": s.pl_label,
                                "current": s.decode(wire),
                                "severity": severity,
                                "note": note,
                            }
                        )
                report[label] = {
                    "udid": udid,
                    "issues": findings,
                    "counts": {
                        "bad": sum(1 for f in findings if f["severity"] == "bad"),
                        "warn": sum(1 for f in findings if f["severity"] == "warn"),
                    },
                    "menu_errors": menu_errors_by_module.get(udid) or {},
                }
        drift = []
        if len(targets) > 1:
            for name, by_mod in all_known.items():
                if len(set(by_mod.values())) > 1:
                    s = SETTINGS_BY_NAME[name]
                    drift.append(
                        {
                            "name": name,
                            "label": s.pl_label,
                            "per_module": {m: s.decode(v) for m, v in by_mod.items()},
                        }
                    )
        return ok_response(per_module=report, drift=drift)

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def get_alarms(
    from_date: str | None = None,
    to_date: str | None = None,
    alarm_type: str = "all",
    module: str | None = None,
) -> dict:
    """Pull alarm/warning/notification history for a date range.

    Args:
        from_date: ISO date `YYYY-MM-DD`. Default: 30 days ago.
        to_date: ISO date. Default: today.
        alarm_type: One of `all` (default), `alarm`, `warning`, `notification`.
        module: Optional module override.

    Returns: `{ok, alarms: [...]}`.
    """

    def _impl() -> dict:
        today = dt.date.today()
        to_d = to_date or today.isoformat()
        from_d = from_date or (today - dt.timedelta(days=30)).isoformat()
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            data = api.alarm_history(
                udid, from_date=from_d, to_date=to_d, alarm_type=alarm_type
            )
        return ok_response(alarms=data, range={"from": from_d, "to": to_d, "type": alarm_type})

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def get_temperature_history(
    period: str = "day",
    month: int | None = None,
    year: int | None = None,
    module: str | None = None,
) -> dict:
    """Per-zone temperature time-series.

    Args:
        period: `day` (last ~24h, ~1 sample/min, ~1200 points/zone) or `week`
                (last 7 days). `year`/`total` are rejected by the server.
        month: For specific month: 1-12, requires `year`.
        year: 4-digit year (with `month`).
        module: Optional module override.

    Returns: `{ok, period, status, data: {history: {<key>: [{x, y}, ...]}}}`
    where `<key>` is an opaque TECH identifier ending with the zone name
    (split on `|` and take the last segment to get the readable name);
    `x` is a `YYYYMMDDhhmm` timestamp string and `y` is °C.

    For multi-month ranges, prefer the CLI `emodul stats dump --since 6m` —
    running long stats fetches from an MCP tool may exceed Claude Desktop's
    ~60s tool timeout.
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            data = api.stats_linear(udid, period=period, month=month, year=year)
        return ok_response(period=period, **data)

    return await anyio.to_thread.run_sync(_impl)


# ---------------------------------------------------------------- WRITE tools


_WRITE_ANNOTATIONS = ToolAnnotations(destructiveHint=True, idempotentHint=False)


@mcp.tool(annotations=_WRITE_ANNOTATIONS)
@safely
async def set_zone_temperature(
    zone: str,
    celsius: float,
    module: str | None = None,
    wait: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Set a zone's setpoint to a constant temperature.

    Args:
        zone: Zone name (substring) or numeric ID.
        celsius: Target temperature in °C, 5.0–35.0.
        module: Optional module override.
        wait: Block until the controller acknowledges (~5-30s). Default true.
        timeout: Max seconds to wait for `duringChange` to clear.

    Returns: `{ok, zone_id, set_c, settled, response}`. `settled=false` means
    the write was accepted but the controller's response was delayed — the
    new value will reflect on next poll.

    Mode after write: `constantTemp` (no schedule). The previous mode is
    overridden until next change.
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
            row = _resolve_zone_helper(flatten_zones(snap), zone)
            if not row:
                raise LookupError(f"Zone not found or ambiguous: {zone}")
            resp = api.set_zone_constant_temp(
                udid,
                mode_id=row["mode_id"],
                zone_id=row["zone_id"],
                set_temperature_int10=temp_to_api(celsius),
            )
            settled = True
            if wait:
                settled = api.wait_until_settled(
                    lambda: api.is_zone_settled(udid, row["zone_id"]),
                    timeout=timeout,
                )
        return ok_response(
            zone_id=row["zone_id"],
            zone_name=row["name"],
            set_c=celsius,
            settled=settled,
            response=resp,
        )

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool(annotations=_WRITE_ANNOTATIONS)
@safely
async def boost_zone(
    zone: str,
    celsius: float,
    minutes: int,
    module: str | None = None,
    wait: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Temporary boost: hold a zone at `celsius` for N minutes, then revert.

    Args:
        zone: Zone name or ID.
        celsius: Target °C (5.0-35.0).
        minutes: 1-1440 (24h max).
        module: Optional module override.
        wait: Block until settled.

    Returns: `{ok, zone_id, minutes, settled, response}`. Mode after write:
    `timeLimit`. The controller automatically reverts to the previous mode
    after `minutes` elapse.
    """

    def _impl() -> dict:
        if not 1 <= minutes <= 1440:
            raise ValueError("minutes must be 1-1440")
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
            row = _resolve_zone_helper(flatten_zones(snap), zone)
            if not row:
                raise LookupError(f"Zone not found or ambiguous: {zone}")
            resp = api.set_zone_time_limit(
                udid,
                mode_id=row["mode_id"],
                zone_id=row["zone_id"],
                set_temperature_int10=temp_to_api(celsius),
                minutes=minutes,
            )
            settled = api.wait_until_settled(
                lambda: api.is_zone_settled(udid, row["zone_id"]),
                timeout=timeout,
            ) if wait else True
        return ok_response(
            zone_id=row["zone_id"],
            zone_name=row["name"],
            minutes=minutes,
            set_c=celsius,
            settled=settled,
            response=resp,
        )

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool(annotations=_WRITE_ANNOTATIONS)
@safely
async def toggle_zone(
    zone: str,
    on: bool,
    module: str | None = None,
    wait: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Turn a zone fully on (zoneOn) or off (zoneOff).

    Args:
        zone: Zone name or ID.
        on: true = `zoneOn`, false = `zoneOff` (disables heating regardless
            of setpoint — useful for summer / unused rooms).
        module: Optional module override.

    Returns: `{ok, zone_id, new_state, settled, response}`.
    """

    def _impl() -> dict:
        state = "zoneOn" if on else "zoneOff"
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
            row = _resolve_zone_helper(flatten_zones(snap), zone)
            if not row:
                raise LookupError(f"Zone not found or ambiguous: {zone}")
            resp = api.set_zone_state(udid, zone_id=row["zone_id"], state=state)
            settled = api.wait_until_settled(
                lambda: api.is_zone_settled(udid, row["zone_id"]),
                timeout=timeout,
            ) if wait else True
        return ok_response(
            zone_id=row["zone_id"],
            zone_name=row["name"],
            new_state=state,
            settled=settled,
            response=resp,
        )

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool(annotations=_WRITE_ANNOTATIONS)
@safely
async def attach_schedule(
    zone: str,
    schedule_index: int,
    module: str | None = None,
) -> dict:
    """Switch a zone to use a globalSchedule slot.

    Args:
        zone: Zone name or ID.
        schedule_index: 0-4 (globalSchedule slot). Use `list_schedules` to
                        see what each slot contains.
        module: Optional module override.

    Returns: `{ok, response}`. Implementation calls
    `POST /zones/{id}/global_schedule` with `setInZones=[{modeId, zoneId}]` —
    the only working endpoint for attaching schedules (the obvious
    `POST /zones` returns 422).
    """

    def _impl() -> dict:
        with open_api() as (api, cfg):
            udid = resolve_udid(module, api, cfg)
            snap = api.get_module(udid)
            row = _resolve_zone_helper(flatten_zones(snap), zone)
            if not row:
                raise LookupError(f"Zone not found or ambiguous: {zone}")
            gs = (snap.get("zones") or {}).get("globalSchedules") or {}
            elements = gs.get("elements") or []
            sched = next((s for s in elements if s.get("index") == schedule_index), None)
            if not sched:
                available = [s.get("index") for s in elements]
                raise LookupError(
                    f"globalSchedule idx={schedule_index} not found. Available: {available}"
                )
            resp = api.attach_global_schedule(
                udid,
                zone_id=row["zone_id"],
                mode_id=row["mode_id"],
                schedule_element=sched,
            )
        return ok_response(
            zone_id=row["zone_id"],
            zone_name=row["name"],
            schedule_index=schedule_index,
            schedule_name=sched.get("name"),
            response=resp,
        )

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool(annotations=_WRITE_ANNOTATIONS)
@safely
async def update_setting(
    name: str,
    value: str,
    all_modules: bool = False,
    module: str | None = None,
    wait: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Update a named controller parameter (e.g. emergency-mode, hysteresis).

    Args:
        name: Slug from `settings list` — one of: emergency-mode, hysteresis,
              sigma-range, antifreeze, weather-control, cooling, heating,
              optimum-start, sensor-calibration, diagnostic-file, show-all,
              temp-max, temp-min, preset-comfort, preset-eco, preset-holiday, etc.
        value: Display value (°C as float, % as int, "on"/"off" for bool).
        all_modules: Apply to every controller on the account.
        module: Single module when `all_modules=False`.

    Returns: `{ok, name, label, wire_value, display, applied_to: [...]}`.
    """
    from emodul.commands.menu import _pin_chain

    def _impl() -> dict:
        s = SETTINGS_BY_NAME.get(name)
        if not s:
            known = ", ".join(sorted(SETTINGS_BY_NAME))
            raise ValueError(f"Unknown setting {name!r}. Known: {known}")
        wire = s.encode(value)
        with open_api() as (api, cfg):
            if all_modules:
                targets = [m["udid"] for m in api.list_modules() if m.get("udid")]
            else:
                targets = [resolve_udid(module, api, cfg)]
            results = []
            for udid in targets:
                # Narrow exception scope to known API/network failures so that
                # genuine bugs (KeyError, AttributeError) propagate to `safely`
                # and get a full traceback rather than silent per-target masking.
                try:
                    resp = api.set_menu_param(udid, s.menu_type, s.ido, {"value": wire})
                    settled = True
                    if wait:
                        pin_chain = _pin_chain(cfg, udid, s.menu_type) or None
                        settled = api.wait_until_settled(
                            lambda u=udid, pc=pin_chain: api.is_menu_item_settled(
                                u, s.menu_type, s.ido, pin_chain=pc
                            ),
                            timeout=timeout,
                        )
                    results.append(
                        {"udid": udid, "ok": True, "settled": settled, "response": resp}
                    )
                except EmodulApiError as exc:
                    results.append(
                        {
                            "udid": udid,
                            "ok": False,
                            "error": f"API {exc.status} on {exc.path}: {exc.body}",
                            "status": exc.status,
                        }
                    )
        # Aggregate: if ANY target failed, the top-level envelope is NOT ok.
        ok_count = sum(1 for r in results if r["ok"])
        all_ok = ok_count == len(results)
        payload = {
            "name": s.name,
            "label": s.pl_label,
            "wire_value": wire,
            "display": s.decode(wire),
            "applied_to": results,
            "ok_count": ok_count,
            "fail_count": len(results) - ok_count,
        }
        if all_ok:
            return ok_response(**payload)
        return err_response(
            f"{len(results) - ok_count}/{len(results)} targets failed",
            code="partial_failure",
            **payload,
        )

    return await anyio.to_thread.run_sync(_impl)


# ---------------------------------------------------------------- AUTH tools


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True, idempotentHint=True))
@safely
async def login_browser(timeout: int = 300, ctx: Context | None = None) -> dict:
    """Start an interactive browser login. The agent must show the URL to the user.

    Spins up a local 127.0.0.1 server, attempts to open the user's default
    browser, and waits for them to submit credentials in the form. The
    password is sent ONLY to emodul.pl — never reaches the AI agent.

    Args:
        timeout: Max seconds to wait for the user to complete login. Note
                 that Claude Desktop's tool ceiling is ~60s; for chat agents
                 without `resetTimeoutOnProgress` support, run
                 `emodul auth login --browser` from a host terminal instead.

    Returns: `{ok, email, user_id, url, keychain_ok, warning?}` on success.
        The `url` is also sent as an MCP log notification while blocking —
        surface it to the user immediately. `keychain_ok=False` means the
        token works now but auto-refresh on next expiry will fail; the
        warning text explains the remediation.
    """
    from emodul import auth as auth_kc
    from emodul.config import Config
    from emodul.web_auth import web_login_flow

    captured_url: list[str] = []

    def _on_url(url: str) -> None:
        captured_url.append(url)
        log.info("browser login URL: %s", url)
        if ctx is not None:
            # Best-effort: send an MCP log message that surfaces the URL in
            # clients that support log notifications. `send_log_message` is
            # async and we're on a worker thread, so use `from_thread.run`
            # (which awaits coroutines). Failures are intentionally swallowed
            # but logged at debug level so they're not invisible.
            try:
                anyio.from_thread.run(
                    ctx.session.send_log_message,
                    "info",
                    f"Open this URL to sign in: {url}",
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("MCP log notification failed (non-fatal): %r", exc)

    def _impl() -> dict:
        cfg = Config.load()
        result = web_login_flow(
            base_url=cfg.base_url,
            language_id=18,
            open_browser=True,
            port=None,
            timeout=timeout,
            on_url=_on_url,
        )
        # Persist token first; keychain is best-effort but surfaced.
        new_cfg = cfg.with_updates(
            token=result["token"],
            user_id=result["user_id"],
            email=result["email"],
        )
        new_cfg.save()
        keychain_ok = True
        keychain_error: str | None = None
        try:
            auth_kc.set_password(result["email"], result["password"])
        except Exception as exc:  # noqa: BLE001
            keychain_ok = False
            keychain_error = str(exc)
            log.warning("keychain set failed: %s", exc)
        out: dict[str, Any] = dict(
            email=result["email"],
            user_id=result["user_id"],
            url=captured_url[0] if captured_url else None,
            keychain_ok=keychain_ok,
        )
        if not keychain_ok:
            out["warning"] = (
                "Password not stored in OS keychain — login works now but "
                f"auto-refresh will fail on next token expiry ({keychain_error}). "
                "User will need to re-run login_browser when this happens."
            )
        return ok_response(**out)

    return await anyio.to_thread.run_sync(_impl)


@mcp.tool()
@safely
async def set_default_module(module: str) -> dict:
    """Set the user's default module for subsequent tool calls.

    Args:
        module: Module name (substring) or full udid.

    Returns: `{ok, default_udid, name}`. Persisted to config.json.
    """

    def _impl() -> dict:
        from emodul.config import Config

        with open_api() as (api, _cfg):
            mods = api.list_modules()
            from emodul._resolver import resolve_module_udid as _resolve

            udid = _resolve(module, mods)
            match = next((m for m in mods if m["udid"] == udid), None)
        # _resolve has a fast-path for full-hex udids that doesn't verify
        # the udid actually exists on this account — guard against persisting
        # a bogus default.
        if match is None:
            raise LookupError(
                f"Module {module!r} resolves to udid {udid} which is not on "
                "this account. Call `list_modules` to see what's available."
            )
        cfg = Config.load()
        new_cfg = cfg.with_updates(default_udid=udid)
        new_cfg.save()
        return ok_response(default_udid=udid, name=match.get("name"))

    return await anyio.to_thread.run_sync(_impl)


# ---------------------------------------------------------------- entry point


def main() -> None:
    """Run the MCP server on stdio. Called by `emodul mcp` and `emodul-mcp`."""
    log.info("emodul MCP server starting (stdio transport)")
    mcp.run()


if __name__ == "__main__":
    main()
