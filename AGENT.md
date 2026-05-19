# Agent Setup Prompt

**One-shot setup prompt for AI agents** (Claude Code, Codex CLI, Gemini CLI,
Cursor — anything that can run shell commands and read files).

To use: paste the URL of this file into your agent:

```
Follow this setup prompt step by step:
https://raw.githubusercontent.com/hculap/emodul/main/AGENT.md
```

The agent will read this file and execute the steps below.

---

## Agent instructions (read and execute in order)

You are configuring the `emodul` CLI for the user. It is a Python CLI for
Polish TECH Sterowniki / eModul.pl floor-heating controllers. Goal: end
state where the user can ask you "set Salon to 22 °C" in any future
session and you can do it.

### Step 1 — Install the CLI

```bash
pipx install emodul
```

If `pipx` is not available, fall back in order:
1. Install pipx: `brew install pipx` (macOS) or `apt install pipx` (Debian/Ubuntu) or `python3 -m pip install --user pipx && pipx ensurepath`
2. If still impossible: `python3 -m venv ~/.emodul-venv && ~/.emodul-venv/bin/pip install emodul`, then alias `emodul=~/.emodul-venv/bin/emodul`

Verify:

```bash
emodul --version
```

Expected: `emodul, version <semver>` where major.minor.patch ≥ 0.1.1.

### Step 2 — Install the bundled Claude Skill

```bash
emodul skill install
```

This drops `SKILL.md` at `~/.claude/skills/emodul/SKILL.md`. Future Claude
Code sessions in any directory will auto-discover the **emodul** skill and
load the full CLI surface into context on heating-related user requests.

For other harnesses (Codex, Gemini), use `emodul skill install --to /path/...`
to put it where they expect skills, or read `emodul skill show` and feed
the contents into the agent's own skill mechanism.

### Step 3 — Authenticate

Ask the user for their **eModul.pl email**. Then run:

```bash
emodul auth login --email <user-email>
```

This will prompt the user (interactively) for their password. The password
is stored in the OS keychain (macOS Keychain / GNOME Keyring / KWallet) so
the CLI silently re-authenticates on any future 401.

Alternative if the user already has a JWT (from browser DevTools → Local
Storage → `token` on emodul.pl):

```bash
emodul auth import-token "<jwt>" --user-id <user-id>
```

Verify:

```bash
emodul --json auth whoami
```

Expected: `user_id`, `token_present: true`, `server_info` populated.

### Step 4 — Pick a default controller

```bash
emodul --json modules list
```

Read the response — typically 1-2 controllers (`Parter`, `Piętro`, etc.).
Ask the user which one to set as default, then:

```bash
emodul modules select <module-name-or-udid>
```

After this, all subsequent commands without `-m` operate on the default
module.

### Step 5 — Cache Polish translations (one-time, ~5 s)

```bash
emodul i18n refresh
```

Needed to translate `txtId` references in tiles and menus.

### Step 6 — Confirm

Run a final smoke test:

```bash
emodul status
```

Should print a rich table of all zones in the default module. If yes,
setup is complete. Report success to the user and offer:

- `emodul --json settings audit` to find any non-default heating config
- `emodul --json zones list -a` for a cross-controller view
- `emodul watch install-service` to start a background SQLite logger of
  all relay transitions

The skill is now installed permanently — future Claude Code sessions in
any directory will automatically know about the **emodul** skill and can
drive this CLI on heating-related requests without further setup.

---

## What the user can ask you after setup completes

| User says | You run |
|---|---|
| "What's the temperature in Salon?" | `emodul --json status` → read zone `Salon` |
| "Ustaw Łazienkę na 22.5" | `emodul zones set-temp "Łazienka" 22.5` |
| "Podgrzej Sypialnia na 23 na 2 godziny" | `emodul zones boost "Sypialnia" 23 120` |
| "Sprawdź czy ogrzewanie jest dobrze ustawione" | `emodul --json settings audit` |
| "Pokaż harmonogramy na piętrze" | `emodul --json schedules list -m Piętro` |
| "Wyłącz Garaż" | `emodul zones off "Garaż"` |
| "Were there any alarms?" | `emodul --json alarms history` |

Full reference is in the installed skill at `~/.claude/skills/emodul/SKILL.md`
(or `emodul skill show`).

---

## Safety constraints

- **Always pass `--json`** when parsing output. The default text output is
  rich-table formatted and contains ANSI codes.
- **Writes block until settled** (~5-30 s) by default — that's expected;
  don't time out aggressively.
- **Never paste the user's JWT, `user_id`, controller `udid`, email, or
  password in any visible output, log, or commit**.
- **Don't `curl` the API directly**. The CLI handles auth refresh,
  duringChange race window, PIN injection, unit conversion. Use it.
- **MP (manufacturer) menu PIN is unknown** — don't attempt 5162 on MP,
  it returns 422. MS (service) PIN 5162 is auto-stored after first unlock.
- **Off-season caveat**: in summer (May-Sep) Polish users often turn the
  furnace off entirely; zones may chronically sit below setpoint with
  `action: idle`. Don't diagnose hardware faults from off-season data.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `pipx: command not found` | Not installed | `brew install pipx` / `apt install pipx` |
| `emodul: command not found` after install | pipx PATH not added | `pipx ensurepath`, restart shell |
| `API 401` after auth | JWT expired or wrong creds | re-run `emodul auth login` |
| `SKILL.md not found in package` | Old version (< 0.1.1) | `pipx upgrade emodul` |
| `No module selected` | Default udid not set | `emodul modules select <name>` |
| Stats `Invalid range` | Asked for year/total | Use `--period day|week` or `stats dump --since` |

Setup ends successfully when `emodul status` prints a zone table without
errors.
