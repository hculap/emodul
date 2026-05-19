---
name: emodul
description: |
  Controls a Polish Tech Sterowniki / eModul.pl floor-heating system via a local Python CLI. Reads zones, sets setpoints, attaches schedules, audits configuration, pulls historical stats, runs a background SQLite transition logger. Use whenever the user mentions heating, room temperature, floor heating, ogrzewanie, any room thermostat ("Salon", "Łazienka", "Sypialnia", "Pokój", "Biuro", "Garaż", "Kuchnia", "Parter", "Piętro"), wants to "set", "change", "raise", "boost", "turn on/off" any zone, asks to "check" or "audit" heating, asks about TECH controllers (L-4X, L-8, L-12), eModul cloud, weekly heating schedules, serwis menu / PIN 5162, alarm history, or historical temperature data. Also triggers on Polish: "ustaw temperaturę", "podgrzej", "włącz/wyłącz ogrzewanie", "ile stopni", "harmonogram grzania". This CLI is the ONLY safe interface — never curl the API directly.
---

# emodul — Tech Sterowniki / eModul.pl CLI skill

## Overview

`emodul` is a Python CLI (and MCP server) for the eModul.pl cloud API used by Polish Tech Sterowniki floor-heating controllers (L-4X WIFI, L-8, L-9, L-12). It handles JWT auth with keychain-backed refresh, exposes both raw and high-level (named-slug) parameter control, decodes Polish menu trees, and bundles a long-running watcher that logs relay/zone transitions to SQLite.

Every command supports `--json` for machine-parseable output. The user's setup typically has 1-2 controllers ("Parter" = ground floor, "Piętro" = upstairs) with 3-5 zones each.

**Two ways an AI agent can drive it**:
- **CLI directly** (this skill — for Claude Code / Codex CLI / Cursor agent mode / Aider). Run `emodul <subcommand> --json` from bash.
- **MCP server** (for Claude Desktop / Cursor chat / Continue / Cline / Zed / JetBrains). Add `{"command": "emodul", "args": ["mcp"]}` to the client's MCP config. ~16 tools available natively. See [AGENT.md](README.md) Path A.

**Binary**: `emodul` (installed via `pipx install emodul`; falls back to `pip install --user emodul`)
**Run from**: any directory (binary uses absolute config path)
**Full reference**: see `README.md` next to this file when Quick Start isn't enough.

## Safety Rules

- **Always pass `--json`** when parsing output programmatically. Text output is rich-table-formatted and includes ANSI codes — don't try to grep it.
- **Writes block by default until settled** (~5-30 s) — the controller reports `duringChange:"t"` and OLD values for up to 30 s after a POST. The CLI waits; pass `--no-wait` only if the user explicitly wants fire-and-forget.
- **Temperatures are Celsius with 0.1 °C precision**. The wire uses integer tenths (21.5 °C → 215) but the CLI handles conversion — always speak in °C to the user and the CLI.
- **Zone selectors accept name OR id**. Names are matched case-insensitively as substrings (`Salon` matches; `salon` matches). If the user names a non-existent zone, the CLI exits with a clear error — don't retry with raw IDs.
- **Module selectors (`-m`)** accept name substring (`Parter`), full udid (32 hex chars), or unique prefix. Without `-m` the CLI uses the default module (`emodul modules select <name>` once).
- **Never put PINs in `--json` outputs the user can see**. PIN 5162 (service menu MS) is stored automatically in config after `emodul menu unlock`. Don't log or echo it.
- **Don't use `emodul raw POST/PUT/DELETE`** unless the user asks for an undocumented endpoint. There's a named command for every routine operation.
- **Heating season matters**: in summer (May-Sep) the user often turns the furnace off, so zones may chronically sit below setpoint and the per-zone relay stays "off" even though the system "works". Don't diagnose hardware faults from temperature data alone during off-season.

## Quick Start

```bash
BIN=/path/to/emodul/.venv/bin/emodul

# Current state of all zones in default module (human view):
$BIN status

# All zones across BOTH controllers (parseable for AI agent):
$BIN --json zones list -a

# Set a zone setpoint (waits until controller acknowledges, ~5-30 s):
$BIN zones set-temp Salon 21.5

# Temporary boost: 23 °C for 90 minutes, then revert to schedule/constant:
$BIN zones boost Łazienka 23 90

# Toggle a zone on / off:
$BIN zones on Salon
$BIN zones off Garaż

# Audit configuration on every controller — flags bad / non-default values:
$BIN --json settings audit

# Pull last 7 days of per-zone temperature curves:
$BIN --json stats linear --period week

# Show what background watcher is recording:
$BIN watch status
```

## When to Use (intent → command)

| User intent (any language) | Command |
|---|---|
| "What's the temperature in X?" / "ile stopni w X?" | `emodul --json status` then read zone X |
| "Set X to N degrees" / "ustaw X na N stopni" | `emodul zones set-temp "X" N` |
| "Heat X to N for N minutes" / "podgrzej X na N min" | `emodul zones boost "X" N MINUTES` |
| "Turn off heating in X" | `emodul zones off "X"` |
| "Is the heating system OK?" / "sprawdź ogrzewanie" | `emodul --json settings audit` then summarize |
| "Show heating history" | `emodul --json stats linear --period week` |
| "Show all my schedules" / "harmonogramy" | `emodul schedules list -m <module>` |
| "Switch X to use schedule Y" | `emodul zones schedule "X" --mode global --index Y` |
| "List my controllers / modules" | `emodul --json modules list` |
| "Were there any alarms?" | `emodul --json alarms history` |
| "Set up auto-logging in background" | `emodul watch install-service` |
| "Stop the background logger" | `emodul watch uninstall-service` |
| User asks something not covered above | `emodul --help` then drill into the right subcommand |

## Commands reference

Twelve subcommand groups. Always read `--help` on the specific subcommand for full flag list. Below are the most-used invocations grouped by purpose.

### `zones` — read & control individual heating zones

```bash
emodul --json zones list                  # default module
emodul --json zones list -a               # all modules (adds Module column + module_short/module_name fields)
emodul --json zones show "Salon"          # full data incl. raw JSON
emodul zones set-temp "Salon" 21.5        # constantTemp, blocks until settled
emodul zones set-temp "Salon" 21.5 --no-wait     # fire-and-forget
emodul zones boost "Łazienka" 23 90       # timeLimit mode: hold 23 °C for 90 min
emodul zones on "Salon"                   # zoneOn
emodul zones off "Garaż"                  # zoneOff (e.g. summer)
emodul zones rename "Salon" "Living"
emodul zones schedule "Salon" --mode global --index 0   # attach globalSchedule slot 0
emodul zones audit                        # behavioural analysis: mean/min/max/stdev/gap vs setpoint
emodul zones audit --period week
```

### `settings` — high-level named-slug parameters (preferred over raw `menu`)

25 named slugs across MU/MI/MS categories. Run `emodul --json settings list` to enumerate.

```bash
emodul --json settings list                                       # inventory
emodul --json settings show                                       # dashboard for default module
emodul --json settings show --category safety                     # filter by category
emodul --json settings show --include-locked                      # show items the server reports as access=false
emodul --json settings get emergency-mode -m Parter
emodul settings set emergency-mode 30                             # writes; blocks until settled
emodul settings set diagnostic-file off --all-modules             # mass-apply
emodul --json settings audit                                      # bad/warn items + cross-module drift detection
```

Common slug names: `emergency-mode`, `hysteresis`, `sigma-range`, `weather-control`, `cooling`, `heating`, `antifreeze`, `optimum-start`, `sensor-calibration`, `diagnostic-file`, `show-all`, `temp-max`, `temp-min`, `preset-comfort`, `preset-eco`, `preset-holiday`.

### `schedules` — globalSchedule introspection

Each controller has exactly 5 globalSchedule slots (idx 0-4).

```bash
emodul --json schedules list -m Parter       # all 5 with day mask, intervals, used-by zones
emodul --json schedules show 0 -m Parter     # detail by index
emodul --json schedules show "Sypialnia" -m Piętro    # detail by name
```

Schedules are decoded: day mask `Pn Wt Śr Cz Pt — —` (weekday), intervals as `06:00-21:00 → 21.5 °C`, setback temperature for off-hours.

### `stats` — historical telemetry

```bash
emodul --json stats available -m Parter                                # what series exist
emodul --json stats linear --period day                                # today's per-zone temp curves
emodul --json stats linear --period week
emodul --json stats linear --month 4 --year 2026                       # specific month
emodul --json stats column consumptions --period month --month 4 --year 2026
emodul stats csv consumptions --month 4 --year 2026 --out apr.csv

# Multi-month batch (server rejects --period year/total):
emodul --json stats dump --since 2025-10 --until 2026-05
emodul --json stats dump --since 6m                                    # 6 months ago → now
emodul --json stats dump --since 1y --kind csv --state consumptions --out year.csv
```

Note: `--period day` and `--period week` are the only bare periods that work. `year` and `total` return 422. For longer ranges use `stats dump`.

### `modules` — list & switch controllers

```bash
emodul --json modules list                            # all controllers on the account
emodul modules select "Parter"                        # set default module
emodul modules show -m Piętro --zones-only            # zone snapshot
emodul modules sync -m Parter                         # force fresh data pull (rate-limited)
```

### `alarms` — alarm/warning history

```bash
emodul --json alarms history                          # last 30 days, all types
emodul --json alarms history --from 2026-04-01 --to 2026-05-18 --type warning
emodul alarms ack 123                                 # dismiss popup by id
```

### `tiles` — dashboard tiles (pumps, relays, version)

```bash
emodul --json tiles list --translate -m Parter        # decodes txtId via Polish i18n
```

Common tile types: `11` = Relay (e.g. "Pompa" = pump, "Styk beznapięciowy" = dry contact). Each has `params.workingStatus` bool.

### `menu` — raw MU/MI/MS access (advanced; prefer `settings`)

```bash
emodul --json menu show MU -m Parter                  # user menu (no PIN)
emodul --json menu show MI -m Parter                  # fitter menu (no PIN)
emodul menu unlock MS 0 5162 -m Parter                # service-menu PIN — stored permanently
emodul --json menu show MS -m Parter                  # subsequent reads auto-include PIN
emodul menu set MI 3145755 30 -m Parter               # raw ido write (advanced)
```

MP (manufacturer menu) PIN is **unknown** — don't try 5162 there, it returns 422.

### `watch` — long-running transition logger

```bash
emodul watch run --once                               # single poll, dump state to DB, exit
emodul watch run                                      # foreground loop, Ctrl-C to stop
emodul watch status --limit 50                        # recent events + service health
emodul watch install-service --interval 60            # background service (launchd/systemd)
emodul watch uninstall-service                        # stop + remove
```

Database: `~/.local/state/emodul/state.db` (SQLite). Tables: `tile_events` (Pompa, Styk on/off), `zone_events` (setpoint/mode/relay changes), `run_log` (errors). Insert-on-change only.

### `auth`, `i18n`, `poll`, `raw`, `status` — utility

```bash
emodul auth whoami                                    # who am I + auto-refresh status
emodul auth login --browser                           # opens local 127.0.0.1 form — agent never sees password (RECOMMENDED in agent contexts)
emodul auth login --terminal --email <e>              # classic stdin prompt (interactive only)
emodul auth import-token "<jwt>" --user-id <id>       # paste JWT manually
emodul i18n lookup 873                                # txtId 873 → "Wersja modułu"
emodul poll                                           # one-shot delta poll (15s SPA cadence)
emodul raw GET '/api/v1/users/{user_id}/modules'      # escape hatch for unknown endpoints
emodul status                                         # alias for `zones list` with table
```

## Conventions

**Temperature**: Celsius, accepts `.5` precision (`21.5`). Internal wire format is `int(c * 10)` but the CLI handles it.

**Time**: `boost` minutes are 1-1440 (24h max). Schedule intervals are minutes-of-day (0-1439).

**Mode strings** (returned in `zone.mode.mode`):
- `constantTemp` — fixed setpoint until changed
- `timeLimit` — boost for N minutes
- `localSchedule` — per-zone schedule
- `globalSchedule` — shared schedule (5 slots per controller)

**Zone states** (returned in `zone.zoneState`):
- `noAlarm` — healthy
- `zoneOn` / `zoneOff` — explicit toggles
- `sensorDamaged`, `noCommunication`, `lowBattery`, `damaged`, `waiting` — fault states (rare)
- `zoneUnregistered` — placeholder slot (auto-filtered)

**Action field** (derived by CLI): `heating` (relay on + heating algorithm), `cooling`, `idle` (relay off, no demand), `off` (zone disabled or unknown).

**Module names** (typical for this user): `Parter` (ground floor) and `Piętro` (upstairs). Both are TECH L-4X WIFI v1.0.13. Use them as `-m` argument directly.

**PIN-protected menus**:
- MU (user) — no PIN
- MI (fitters / installer) — no PIN
- MS (service) — PIN **5162** (already stored in user's config)
- MP (manufacturer) — unknown PIN, don't try

**Humidity**: `0` means "no sensor present", not 0% RH. The CLI returns `None` in JSON.

## Output format

All commands support `--json` (global flag, must appear BEFORE the subcommand group):

```bash
emodul --json zones list
emodul --json settings audit
```

JSON output is canonical. Text output adds rich-table formatting that won't parse cleanly.

**Exit codes**:
- `0` — success
- `1` — user error (bad args, zone not found)
- `2` — API error (401, 4xx, 5xx). On 401 the CLI prints `Token rejected` and suggests `emodul auth import-token`.

**Errors on stderr**: API errors print to stderr as `API <code> on <path>: {body}`. JSON success goes to stdout. Pipe `2>/dev/null` if you only want JSON.

## Config & prerequisites

- **Auth state**: `~/.config/emodul/config.json` (chmod 600). Contains `{token, user_id, email, default_udid, pins}`.
- **Password (optional)**: stored in OS keychain under service `emodul` for auto-refresh on 401. Set by `emodul auth login`.
- **i18n cache**: `~/.config/emodul/i18n_pl.json` (~757 KB Polish dictionary). Refresh with `emodul i18n refresh` if menu labels look like `txtId 1234`.
- **Watcher DB**: `~/.local/state/emodul/state.db` (SQLite WAL mode).
- **Watcher service**: `~/Library/LaunchAgents/com.emodul.watcher.plist` (macOS) or `~/.config/systemd/user/emodul-watcher.service` (Linux).
- **Environment override**: `EMODUL_CONFIG_DIR` and `EMODUL_STATE_DIR` for non-default locations.

## Failure modes & recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| `API 401 on …` | JWT expired/invalidated | `emodul auth login` to get fresh token; if keychain has password, auto-refresh should handle |
| `API 422 'Invalid range'` on stats | `--period year` or `--period total` | Use `--period day|week` or `stats dump --since` |
| `API 422 'Invalid JSON data'` on `/zones` | Trying to set schedule mode via raw `POST /zones` | Use `emodul zones schedule X --mode global --index N` (uses `/zones/{id}/global_schedule`) |
| `zone X not found` | Wrong name substring | `emodul --json zones list -a` to see what exists |
| `No module matches X` | `-m` doesn't match any name/udid | `emodul --json modules list` |
| `API 406 with time_left` on sync | Rate-limited | Wait the time, or skip — data freshness is usually fine |
| `menu MS unavailable` | PIN not stored / expired | `emodul menu unlock MS 0 5162 -m <module>` |
| Set succeeded but `get` shows old value | `duringChange:"t"` race window | Wait — by default `set` already blocks until settled; if `--no-wait` was used, wait ~30 s |

## Resources

- **`README.md`** (same directory) — full architecture, endpoint map, wire conventions, security notes. Read when Quick Start isn't enough.
- **`emodul/settings_map.py`** — all 25 named-slug definitions with `(menu_type, ido, kind, recommended_range, bad_values)`.
- **`emodul/api.py`** — the HTTP wrapper; every endpoint is a method. Use as canonical reference for what's possible.
- **External clients worth knowing about** (for cross-reference if the user mentions them):
  - Home Assistant integration: `mariusz-ostoja-swierczynski/tech-controllers` — same API, different surface.
  - Homebridge plugin: `kamil-bednarek/homebridge-tech-emodul` — minimal subset.

Do NOT use `curl` or `httpx` directly against eModul.pl. Use this CLI — it handles auth refresh, duringChange race window, defensive zone filtering, PIN injection, and unit conversion correctly.
