---
name: emodul-mcp
description: |
  Controls a Polish Tech Sterowniki / eModul.pl floor-heating system via the bundled MCP server. Use this skill when MCP tools `list_zones`, `set_zone_temperature`, `audit_settings`, etc. are available — i.e. inside Claude Desktop, Cursor chat, Continue, Cline, Zed, or JetBrains AI Assistant. DO NOT shell out — there is no terminal in these runtimes; if you also see an `emodul` skill (without `-mcp` suffix), that one is for shell-based agents and you should ignore it. Trigger keywords: heating, room temperature, floor heating, ogrzewanie, any room thermostat (typical Polish zone names: "Salon", "Łazienka", "Sypialnia", "Pokój", "Biuro", "Garaż", "Kuchnia"), "set", "change", "raise", "boost", "turn on/off" any zone, "check" or "audit" heating, TECH controllers (L-4X, L-8, L-12), eModul cloud, weekly heating schedules, serwis menu / PIN 5162, alarm history, historical temperature data. Polish: "ustaw temperaturę", "podgrzej", "włącz/wyłącz ogrzewanie", "ile stopni", "harmonogram grzania". The MCP tools are the ONLY interface in this context.
---

# emodul-mcp — Tech Sterowniki / eModul.pl MCP skill

## Overview

`emodul` exposes 16 MCP tools that read and control eModul.pl cloud floor-heating controllers (Polish manufacturer TECH Sterowniki — models L-4X WIFI, L-8, L-9, L-12). The local `emodul` Python process is the MCP server; this client (Claude Desktop / Cursor chat / etc.) drives it over stdio.

A typical install has 1–2 controllers with 3–5 zones each; controllers are named freely by the user (e.g. one per floor, one per building). **Always call `list_modules` first** to discover what exists — never assume specific module names.

The user has no shell exposed to you here. Reach for an MCP tool for every interaction; the `emodul_*` shell commands documented in the sibling `emodul` skill are unavailable.

## Tool inventory (16)

### Read (9) — safe, no side effects
- `whoami` — auth state + token / refresher status
- `list_modules` — discover controllers; returns name, udid, model, online status
- `get_status` — full snapshot of a module (zones, schedules, tiles)
- `list_zones` — flat list of zones; pass `all_modules=true` for cross-controller view
- `get_zone` — single zone full detail by name substring or numeric id
- `list_schedules` — globalSchedule slots (0-4) decoded: day mask, intervals, setback
- `audit_settings` — walk all 25 named-slug settings, flag bad / non-default values; cross-module drift
- `get_alarms` — alarm + warning history with date filters
- `get_temperature_history` — per-zone temperature curves; period or month/year

### Write (5) — `destructiveHint=true`, client will prompt for confirmation
- `set_zone_temperature` — constantTemp mode; blocks until controller settles (~5-30 s)
- `boost_zone` — timeLimit mode: hold target for N minutes, then revert
- `toggle_zone` — zoneOn / zoneOff (summer-off, etc.)
- `attach_schedule` — bind a zone to globalSchedule slot 0-4
- `update_setting` — write any of the 25 named slugs (emergency-mode, hysteresis, weather-control, ...)

### Auth (2)
- `login_browser` — opens a local 127.0.0.1 form; user types password in BROWSER, never sees the agent. Returns once user submits or after `timeout` seconds.
- `set_default_module` — persist a default `module` so subsequent tool calls don't need to pass it

## Safety rules

- **Always discover before acting.** Don't assume zone names ("Salon", "Łazienka", etc.) or module names — call `list_modules` and `list_zones` first. The user's setup is yours to learn.
- **Narrate before write tools.** `destructiveHint=true` triggers a confirmation prompt in well-behaved clients, but you should still describe what you're about to do ("I'm going to set Salon to 21.5 °C") so the user can correct you without reading the JSON args.
- **Check `ok` on every tool result.** Tool errors arrive as `{ok: false, error, code}` envelopes, NOT exceptions. Codes you'll see:
  - `auth_required` — call `login_browser` first.
  - `login_failed` — login timed out, was cancelled, or bind failed. Don't retry without telling the user.
  - `api_error` — eModul cloud returned 4xx/5xx. `status` field has the HTTP code.
  - `not_found` — module / zone / schedule index doesn't exist; call the relevant `list_*` tool to see what does.
  - `bad_input` — your args are wrong shape (e.g. non-numeric temperature). Re-read the tool description.
  - `internal` — something crashed in the tool body. Server log has the traceback; user is told to check logs. Don't retry.
- **Never log or echo PINs.** Service-menu PIN (typically `5162` on TECH controllers) is stored in config after one `update_setting` to a locked param. Don't include it in summaries.
- **Never log JWT, password, user_id, controller udid, or email** in tool output the user can see. The MCP server already redacts these from its own logs; don't leak them in your prose.
- **Heating season caveat.** In summer (May-Sep) the user often turns the furnace off, so zones may chronically sit below setpoint and per-zone relays stay "off" even though the system "works". Don't diagnose hardware faults from temperature data alone during off-season — ask whether the boiler is on.
- **Long stats fetches risk the client timeout.** Claude Desktop's default tool timeout is ~60 s; long `get_temperature_history` ranges may hit it. If a fetch fails with timeout, narrow the date range and retry in chunks.

## Quick Start

```
1. whoami
   → returns {ok: true, user_id, email, token_present, ...}
   → if token_present is false, call login_browser first

2. list_modules
   → returns [{udid, name, model, online}, ...]
   → store the udid or name of the one the user cares about

3. set_default_module(module="<name from step 2>")
   → so you don't have to pass `module` to every subsequent call

4. list_zones(all_modules=true)
   → cross-controller view; each entry has zone_id, name, current_temp, set_temp, mode, action
```

## When to use (intent → tool)

| User intent (any language) | Tool call |
|---|---|
| "What's the temperature in X?" / "ile stopni w X?" | `get_zone(zone="X")` |
| "Set X to N degrees" / "ustaw X na N stopni" | `set_zone_temperature(zone="X", celsius=N)` |
| "Heat X to N for N minutes" / "podgrzej X na N min" | `boost_zone(zone="X", celsius=N, minutes=M)` |
| "Turn off heating in X" / "wyłącz X" | `toggle_zone(zone="X", on=false)` |
| "Turn on X" / "włącz X" | `toggle_zone(zone="X", on=true)` |
| "Is the heating system OK?" / "sprawdź ogrzewanie" | `audit_settings` then summarize |
| "Show heating history" / "pokaż historię" | `get_temperature_history(period="week")` |
| "Show all my schedules" / "harmonogramy" | `list_schedules` |
| "Switch X to use schedule Y" | `attach_schedule(zone="X", index=Y)` |
| "List my controllers / modules" | `list_modules` |
| "Were there any alarms?" / "alarmy" | `get_alarms` |
| "What's my emergency mode set to?" | `audit_settings` then read the row for `emergency-mode` |
| "Change emergency mode to 30" | `update_setting(slug="emergency-mode", value=30)` |
| User mentions a specific room you haven't seen | `list_zones(all_modules=true)` first |

## Conventions

**Temperature**: Celsius, 0.1 °C precision (e.g. `21.5`). The MCP server handles the wire encoding (integer tenths); you always speak °C.

**Time**: `boost` minutes are 1-1440 (24 h max). Schedule intervals are minutes-of-day (0-1439, server-side).

**Mode strings** (`zone.mode.mode` field):
- `constantTemp` — fixed setpoint until changed
- `timeLimit` — boost for N minutes
- `localSchedule` — per-zone schedule
- `globalSchedule` — shared schedule (5 slots per controller)

**Zone states** (`zone.zoneState`):
- `noAlarm` — healthy
- `zoneOn` / `zoneOff` — explicit toggles
- `sensorDamaged`, `noCommunication`, `lowBattery`, `damaged`, `waiting` — fault states (rare)
- `zoneUnregistered` — placeholder slot (auto-filtered server-side)

**Action field** (derived): `heating` (relay on + heating algorithm), `cooling`, `idle` (relay off, no demand), `off` (zone disabled or unknown).

**Module discovery**: users name their controllers freely. Never hardcode a name — `list_modules` first.

**PIN-protected menus** (auto-handled by `update_setting` for accessible slugs):
- MU (user), MI (fitter) — no PIN
- MS (service) — TECH factory default is `5162`; user runs unlock once and it's persisted
- MP (manufacturer) — unknown PIN, don't try

**Humidity**: `0` means "no sensor present", not 0% RH. Tool returns `null` in JSON.

## Tool result envelope

Every tool returns either:
- **Success**: `{ok: true, ...payload}`. Keys depend on the tool.
- **Error**: `{ok: false, error: "<message>", code: "<symbolic>"}`. See safety rules above for code semantics.

Write tools that block until settled (`set_zone_temperature`, `update_setting`) typically take 5-30 s — the controller reports `duringChange:"t"` and OLD values briefly after a POST. The tool waits, then returns the fresh post-settle snapshot. You don't need to poll yourself.

## Config & prerequisites

The MCP server stores state per host in:
- `~/.config/emodul/config.json` — JWT, user_id, email, default module, PINs (chmod 600)
- OS keychain (service `emodul`) — password for auto-refresh on 401 (set by `login_browser`)
- `~/.config/emodul/i18n_pl.json` — Polish translation cache (~757 KB)
- `~/.local/state/emodul/state.db` — watcher SQLite (only if user enabled background logging via CLI)

Most users will have run `emodul auth login --browser` from their terminal once before exposing the MCP server. If `whoami` shows `token_present: false`, prompt the user to run `login_browser` from this skill instead.

## Failure modes & recovery

| Symptom | Likely cause | Next step |
|---|---|---|
| `{ok: false, code: "auth_required"}` | No token or token rejected | Call `login_browser` (or tell user to `emodul auth login --browser` in a terminal) |
| `{ok: false, code: "api_error", status: 401}` | JWT expired and no keychain password to auto-refresh | Same as above |
| `{ok: false, code: "api_error", status: 422, error: "Invalid range"}` on history | Range too wide for the linear endpoint | Narrow the range (single month or week) |
| `{ok: false, code: "not_found"}` on a zone | Name substring didn't match | Call `list_zones(all_modules=true)` to enumerate |
| `{ok: false, code: "not_found"}` on a module | Module name guessed wrong | `list_modules` |
| Write returns `{ok: true}` but read shows old value | Settle race (unusual; server waits up to 30 s) | Wait ~10 s and re-read; if still stale, report it |
| `login_failed` after `login_browser` | User didn't open the URL, or closed the form, or login timed out | Tell user the URL again (it's in the `url` field of the response); offer to retry |
| Client times out before tool returns | Long `get_temperature_history` over Claude Desktop's ~60 s ceiling | Narrow the date range; multiple smaller calls beat one big one |

## Resources

- **`emodul/mcp/server.py`** in the installed package — canonical source for tool definitions, schemas, and behavior. If a description on a tool doesn't match what you observe, the code wins.
- **`emodul/settings_map.py`** — all 25 named-slug definitions used by `update_setting` and `audit_settings`.
- **`README.md`** (in the source repo) — full architecture, endpoint map, wire conventions, security notes. Not bundled into this skill but available at https://github.com/hculap/emodul.

Do NOT instruct the user to run shell commands like `curl`, `httpx`, or raw `emodul` CLI invocations — those are out of reach in this runtime. If a task genuinely requires the CLI (e.g. setting up the background watcher service), tell the user to run it in their own terminal and stop trying tools.
