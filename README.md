# emodul

[![CI](https://github.com/hculap/emodul/actions/workflows/ci.yml/badge.svg)](https://github.com/hculap/emodul/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Claude Skill](https://img.shields.io/badge/Claude-Skill%20ready-D97757.svg)](SKILL.md)
[![GitHub stars](https://img.shields.io/github/stars/hculap/emodul?style=social)](https://github.com/hculap/emodul/stargazers)

Unofficial Python CLI for the **Tech Sterowniki eModul.pl** cloud
(Polish floor-heating controllers: L-4X WIFI, L-8, L-9, L-12, etc.).

Reverse-engineered from the Angular SPA bundle, hardened against bugs
found in the community [`tech-controllers`](https://github.com/mariusz-ostoja-swierczynski/tech-controllers)
Home Assistant integration, and **designed to be driven by AI agents**
out of the box via the bundled `SKILL.md`.

> ⚠️ **Unofficial.** Not affiliated with TECH Sterowniki Sp. z o.o. or eModul.pl.
> Use against your own account only. The vendor may rate-limit or invalidate
> tokens at any time.

```text
emodul status                          → live zone table with action (heating/idle)
emodul settings audit                  → flags bad/non-default parameters across all controllers
emodul zones set-temp Salon 21.5       → blocks until controller acknowledges (no race on re-read)
emodul watch install-service           → launchd/systemd background poller → SQLite event log
```

---

## Why

- **Drive your floor heating from a terminal.** Set temperatures, attach schedules,
  audit configuration, pull historical data — no clicks, no web UI.
- **Hand it to an AI agent.** Every command supports `--json` for stable
  machine-readable output. The agent doesn't need to know HTTP, JWT or PIN
  handling — only the slug-named commands.
- **Reach things the web SPA hides.** Service menu (PIN 5162) parameters,
  raw statistics, alarm history, multi-controller cross-drift detection,
  long-term transition logging.
- **Survive reboots.** Background watcher installs as a launchd plist (macOS)
  or systemd user unit (Linux). Auto-restarts on crash. Auto-re-authenticates
  on token expiry via OS keychain.

---

## One-line setup for AI agents 🤖

Give your AI agent (Claude Code, Codex, Gemini CLI, Cursor) **just this link**:

```
https://raw.githubusercontent.com/hculap/emodul/main/AGENT.md
```

…and say "follow this setup prompt". The agent will:

1. `pipx install emodul`
2. `emodul skill install` — drops the bundled Claude Skill at `~/.claude/skills/emodul/SKILL.md` so future sessions auto-discover the CLI
3. Ask you for credentials, run `emodul auth login`, select a default module
4. Verify with `emodul status`

After that, "ustaw Salon na 22" / "podgrzej Łazienkę na 23 na 2h" / "sprawdź ogrzewanie" just work in any Claude Code session in any directory.

See [AGENT.md](AGENT.md) for the full prompt.

---

## Install

### From PyPI (recommended)

```bash
pipx install emodul         # isolated install, recommended
# OR
pip install emodul          # plain pip (use a venv on PEP-668 systems)
```

After install, to expose the bundled Claude Skill:

```bash
emodul skill install        # → ~/.claude/skills/emodul/SKILL.md
# OR
emodul skill install --symlink   # live-updates on `pipx upgrade emodul`
```

Verify:

```bash
emodul --version
```

### From source (for development)

```bash
git clone https://github.com/hculap/emodul.git
cd emodul
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/emodul --version
```

On macOS the system Python is PEP-668 externally-managed; `.venv` keeps
things clean. `pipx` handles this automatically. Activate the venv with
`source .venv/bin/activate` if you want plain `emodul` on PATH.

## First-time setup

### Browser flow (recommended — best when an AI agent is driving)

```bash
emodul auth login --browser
```

Opens a local sign-in page (`http://127.0.0.1:<random-port>/`) with an
Apple-style form (dark-mode aware). You type your eModul.pl credentials
into the **browser** — the CLI captures the JWT and stores it. The agent
running this command never sees your password.

The flow auto-selects: `--browser` when stdin isn't a TTY (agent
context), `--terminal` when interactive. Override with explicit
`--terminal` / `--browser`.

### Terminal flow (interactive)

```bash
emodul auth login --terminal --email you@example.com
```

Prompts for the password in stdin.

Either way, the JWT lands in `~/.config/emodul/config.json` (chmod 600)
and your password in the OS keychain (Keychain on macOS, GNOME Keyring /
KWallet on Linux, Credential Locker on Windows). On any future 401 the
CLI silently re-authenticates. Opt out with `--no-keychain`. Remove the
password with `emodul auth forget-password`.

…or paste a JWT you already have (e.g. from DevTools → Application → Local
Storage → `token` on emodul.pl):

```bash
emodul auth import-token "eyJhbGciOi..." --user-id 123456789
# (run `auth login` later to also seed the keychain and enable auto-refresh)
```

Pick a default controller so `-m` becomes optional:

```bash
emodul modules list
emodul modules select Parter           # name substring works
```

Cache the Polish translation dictionary (16,368 entries — used to resolve
`txtId` references in tiles and menus):

```bash
emodul i18n refresh
```

---

## Daily commands

### Status & zones

```bash
emodul status                                    # rich table of all zones in default module
emodul status --json                             # same data, machine-readable

emodul zones list                                # current state per zone
emodul zones list -a                             # cross-module, with "Module" column
emodul zones show Salon                          # full data + raw JSON
emodul zones audit                               # behavioural analysis (mean/min/max/stdev/gap)
emodul zones audit --period week                 # uses /stats/linear

emodul zones set-temp Salon 21.5                 # constantTemp; blocks ~5-30s until settled
emodul zones boost Salon 23 90                   # 23 °C for 90 min, then revert
emodul zones on  Salon
emodul zones off Salon
emodul zones rename Salon "Living"
emodul zones schedule Salon --mode global --index 0      # attach globalSchedule
```

**Zone selector** accepts either a numeric `zone_id` or a unique
case-insensitive name substring.

**`--wait` / `--no-wait`**: all zone writes by default block until the
controller clears its `duringChange:"t"` flag (the API otherwise reports the
OLD value for ~30s — Home Assistant integration issue #184). Disable with
`--no-wait` for fire-and-forget.

### Settings (named parameters, no raw IDOs)

Twenty-five named slugs across MU/MI/MS (no MP — that PIN is unknown).

```bash
emodul settings list                             # inventory: name / label / category
emodul settings show                             # dashboard table with audit verdicts
emodul settings show --category safety           # filter
emodul settings show --include-locked            # show items the server reports as access=false
emodul settings get emergency-mode
emodul settings set emergency-mode 30
emodul settings set diagnostic-file off --all-modules    # apply to every controller
emodul settings audit                            # bad/warn items + cross-module drift detection
```

Slug categories: **safety** (emergency-mode, antifreeze, actuator-protection,
temp-max/min), **actuator** (hysteresis, sigma-range, weather-control,
optimum-start, sensor-calibration), **schedule** (heating, cooling, presets),
**diagnostic** (diagnostic-file, show-all).

### Menus (when you need raw IDO access)

```bash
emodul menu show MU                              # user menu (no PIN)
emodul menu show MI                              # fitter menu (no PIN)
emodul menu unlock MS 0 5162                     # one-time PIN unlock — saved to config
emodul menu show MS                              # subsequent reads auto-include PIN
emodul menu set MI 3145755 30                    # raw ido write
emodul menu forget-pins MS                       # wipe saved PINs
```

Type aliases: `user`/`MU`, `fitters`/`MI`, `service`/`MS`,
`manufacturer`/`MP`. **MP PIN is not 5162** — it's a separate code held by
Tech / installers. Not required for normal use.

### Schedules

```bash
emodul schedules list                            # all 5 globalSchedules: day mask, intervals, used-by
emodul schedules show 0                          # detail (by index)
emodul schedules show "Salon i Łazienka"         # detail (by name substring)
```

Each TECH controller has exactly 5 globalSchedule slots. The CLI decodes
day masks (`Pn Wt Śr Cz Pt — —`), interval times (`06:00-21:00 → 21.5 °C`),
and setback temperatures. The `Używają` column lists which zones currently
reference each schedule.

### Statistics

```bash
emodul stats available                                          # what series exist
emodul stats linear --period day                                # today's temp curves
emodul stats linear --period week
emodul stats linear --month 4 --year 2026
emodul stats column consumptions --period month --month 4 --year 2026
emodul stats csv consumptions --period month --month 4 --year 2026 --out apr.csv

# Multi-month batch:
emodul stats dump --since 2025-10 --until 2026-05               # YYYY-MM
emodul stats dump --since 6m                                    # 6 months ago → now
emodul stats dump --since 1y                                    # 1 year ago → now
emodul stats dump --since 12m --kind csv --state consumptions --out year.csv
```

**Periods accepted**: `day`, `week`, and explicit `--month X --year Y`.
`year`/`total` are rejected by the server (422 on L-4X WIFI). For longer
ranges use `stats dump`, which iterates months and merges results into one
payload. Empty months auto-dropped by default (`--keep-empty` overrides).

### Alarms

```bash
emodul alarms history                                           # last 30 days, all types
emodul alarms history --from 2026-04-01 --to 2026-05-18 --type warning
emodul alarms ack 123                                           # acknowledge popup
```

### Tiles, i18n, low-level

```bash
emodul tiles list --translate                                   # decode txtId via i18n cache
emodul i18n refresh                                             # fetch fresh 757 KB PL dictionary
emodul i18n lookup 873                                          # txtId 873 → "Wersja modułu"

emodul poll                                                     # one-shot delta poll
emodul poll --since 1779120000                                  # only changes since epoch

# Escape hatch when you need a not-yet-wrapped endpoint:
emodul raw GET '/api/v1/users/{user_id}/modules'
emodul raw POST '/api/v1/users/{user_id}/modules/{udid}/zones' \
  --body '{"zone":{"id":9002,"zoneState":"zoneOn"}}'
```

`{user_id}` and `{udid}` placeholders are auto-substituted from your config.

---

## Watcher (background process)

Long-running poller that records relay/zone transitions to SQLite. Insert-on-
change only — a year of "nothing happens" stays tiny.

```bash
emodul watch run                                                # foreground, Ctrl-C to stop
emodul watch run --once                                         # single poll then exit
emodul watch run --interval 30                                  # custom poll seconds

emodul watch install-service --interval 60                      # auto-start on boot
emodul watch status                                             # recent events + service health
emodul watch uninstall-service                                  # stop + remove
```

**macOS** → writes `~/Library/LaunchAgents/com.emodul.watcher.plist`,
`launchctl load`s it, sets `KeepAlive` + `ThrottleInterval=60`.
Logs: `tail -f /tmp/emodul-watcher.{out,err}.log`.

**Linux** → writes `~/.config/systemd/user/emodul-watcher.service`,
`systemctl --user enable --now`. ⚠️ Run once: `sudo loginctl enable-linger
$USER` to keep it alive when logged out.
Logs: `journalctl --user -u emodul-watcher -f`.

### What it records

Database at `~/.local/state/emodul/state.db`:

| Table | Captures | When inserted |
|---|---|---|
| `tile_events` | Pompa, Styk beznapięciowy on/off | only on state change |
| `zone_events` | Setpoint, current temp, mode, per-zone relay state | when any of setpoint/mode/relay changes |
| `run_log` | Startup, errors, API failures | each event |

Query examples:

```bash
# Heating intervals for Salon over last 7 days:
sqlite3 -header -column ~/.local/state/emodul/state.db \
  "SELECT datetime(ts,'unixepoch','localtime') AS time, name, relay
   FROM zone_events
   WHERE name='Salon' AND ts > strftime('%s','now','-7 days')
   ORDER BY ts"

# Pump cycles count this month:
sqlite3 ~/.local/state/emodul/state.db \
  "SELECT COUNT(*) FROM tile_events
   WHERE tile_id=8002 AND state=1
     AND ts > strftime('%s','now','start of month')"
```

---

## For AI agents

The CLI is designed to be a clean tool surface for an LLM agent. Conventions:

1. **`--json` on every command** for stable structured output. Default text
   output is human-friendly (rich tables, colors) but `--json` is canonical.
2. **Module selector `-m`** accepts a full 32-char udid, a unique prefix
   (e.g. `abc12345`), or a unique name substring (e.g. `Parter`).
3. **Slug-based settings** (`emodul settings list` enumerates all 25)
   instead of raw IDOs. The agent never has to know that
   "emergency-mode" lives at `MI:3145755:percent`.
4. **`--all-modules`** for cross-controller fan-out where it makes sense
   (`settings set`, `settings audit`, `zones list -a`).
5. **`--no-wait`** for fast fire-and-forget when the agent doesn't care
   about settle confirmation.
6. **`emodul raw <METHOD> <path> [--body JSON]`** is the escape hatch when
   the agent needs an undocumented endpoint. `{user_id}` and `{udid}` are
   auto-substituted.

A typical agent prompt:

> "Use `emodul --json settings audit` to find any non-default config on the
> heating system. Then for each WARN with a clear fix, run the suggested
> `emodul settings set …` command."

---

## Architecture

```
emodul/
  api.py                    httpx wrapper; every endpoint as a method
                            + wait_until_settled / is_*_settled helpers
  auth.py                   keychain-backed refresher (called by ApiClient on 401)
  config.py                 ~/.config/emodul/config.json (chmod 600)
  format.py                 °C ↔ tenths conversion, table rendering, JSON output
  i18n.py                   16K-entry PL dictionary cache
  settings_map.py           25 named parameters → (menu_type, ido, kind, recommend, bad)
  storage.py                SQLite schema for the watcher
  cli.py                    click root group, Ctx with module-name resolver
  commands/
    auth.py                 login / import-token / whoami / logout / forget-password
    modules.py              list / select / show / sync / rename
    zones.py                list / show / set-temp / boost / on / off
                            schedule / rename / schedule-set / audit
    menu.py                 show / unlock / set / forget-pins
    settings.py             list / show / get / set / audit
    schedules.py            list / show
    stats.py                available / linear / column / csv / dump
    alarms.py               history / ack
    misc.py                 tiles / i18n / poll / raw / status
    watch.py                run / status / install-service / uninstall-service
```

### Endpoint map (gist)

- Base: `https://emodul.pl` (the `.pl` and `.eu` share one backend)
- Auth: `Authorization: Bearer <jwt>` — **no cookies, "Bearer " prefix required**
- `POST /api/v1/authentication` → `{token, user_id}`
- `GET /api/v1/users/{uid}/modules` and `…/modules/{udid}` (kitchen sink:
  zones + tiles + schedules)
- `POST /…/zones` for `constantTemp` / `timeLimit` / `zoneOn|zoneOff`
- `POST /…/zones/{zoneId}/global_schedule` to attach a globalSchedule
  (body includes full schedule definition + `setInZones`)
- `GET /…/menu/{MU|MI|MS|MP}[/{id}:{pin},…]` walks menu trees with inline
  PIN injection
- `POST /…/menu/{type}/ido/{id}` writes any parameter
- `GET /api/v1/modules/{udid}/statistics/…` — **no `/users/` prefix here**
- `GET /…/alarm_history/from/{date}/to/{date}/type/{all|alarm|warning|notification}`
- `GET /api/v1/i18n/{lang}` (757 KB Polish dictionary, 16,368 entries)
- `GET /…/update/data/parents/{JSON}/alarm_ids/{JSON}[/last_update/{ts}]` —
  yes, JSON arrays embedded in the URL path

### Wire conventions

- All temperatures are **integer tenths of °C** (`215` = 21.5 °C). The CLI
  accepts/displays Celsius; conversion happens in `format.py`.
- Wire format `7` = tenths °C; `8` = percent; `10` = on/off bool; `106` =
  numeric value (sub-format-dependent).
- `humidity == 0` means **"no sensor"**, not 0% RH — CLI returns `None`.
- After any write, server keeps `duringChange:"t"` for ~5-30s and returns
  the OLD value during that window. CLI by default polls until cleared.

---

## Security

- JWT has no `exp` claim — treat it as a long-lived API key.
- Config at `~/.config/emodul/config.json` is `chmod 600`.
- Password (if `auth login` was used) lives ONLY in the OS keychain.
  Verify on macOS with `security find-generic-password -s emodul -a <email>`.
- **Don't commit** `~/.config/emodul/` or anything in `benchamr/probes/`
  (they may contain JWTs).
- The CLI does not log requests or responses to disk by default. The watcher
  only persists state transitions, never tokens.

---

## Caveats & known limitations

- **MP (manufacturer) menu PIN is unknown.** PIN `5162` works for MS only.
  MP requires a different code that Tech doesn't publish; you don't need it
  for normal use. Antystop-pomp, max floor temperature safety, PID-vs-
  hysteresis algorithm selector all live behind MP and are invisible from
  here.
- **No WebSocket / SSE push channel** on eModul — confirmed by probing.
  All "live" updates come from HTTP polling. The watcher does this.
- **No `/refresh` endpoint** and no long-lived API tokens. The CLI works
  around this with keychain-backed re-auth on 401.
- **Statistics**: `--period year` and `--period total` are rejected by the
  server (`422 Invalid range`). Use `--period day|week` for current data
  or `stats dump --since YYYY-MM` for arbitrary ranges.
- **Some menu items report `access=false`** — server-side gated. `settings
  show` hides them by default; opt-in with `--include-locked`.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, where
new endpoints belong, and how to anonymise bug reports. Project follows
the [Contributor Covenant](CODE_OF_CONDUCT.md).

Have a different TECH controller (L-8, L-9, L-12, …)? Try `emodul status`
against your account and open an issue with whatever breaks — most things
should "just work" since the API shape is shared across models.

## Acknowledgements

This project owes its endpoint map and several hardening patterns to two
community projects:

- [`mariusz-ostoja-swierczynski/tech-controllers`](https://github.com/mariusz-ostoja-swierczynski/tech-controllers) — Home Assistant integration, especially `tech.py` (HTTP wrapper),
  `const.py` (tile-type taxonomy), and the comments in `switch.py` /
  `select.py` / `number.py` documenting the `duringChange:"t"` race.
- [`kamil-bednarek/homebridge-tech-emodul`](https://github.com/kamil-bednarek/homebridge-tech-emodul) — TypeScript Homebridge plugin, narrow but clean; confirmed
  the basic auth + zones POST shape.

Tech Sterowniki publishes no official SDK or schema for eModul itself,
though their [`techsterowniki/sinum-mcp`](https://github.com/techsterowniki/sinum-mcp) repo bundles OpenAPI schemas for their
sibling Sinum product, which confirm wire conventions (×10 temp, unit
codes 0-6) used across their codebase.
