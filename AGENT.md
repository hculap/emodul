# Agent Setup Prompt

Three install paths cover every AI agent runtime in 2026. Pick the one
that matches what you're using.

To use: paste the URL of this file into your agent:

```
Follow this setup prompt step by step:
https://raw.githubusercontent.com/hculap/emodul/main/AGENT.md
```

---

## Pick your runtime

| Your AI agent | Setup path |
|---|---|
| **Claude Desktop** / **Cursor (chat tab)** / **Continue** / **Cline** / **Zed** / **JetBrains AI Assistant** / **OpenCode** | **Path A — MCP server** ↓ |
| **Claude Code (CLI)** / **Codex CLI** / **Cursor (agent mode CLI)** / **Aider** / **Gemini CLI** | **Path B — local CLI install** ↓ |
| **claude.ai (web)** / **ChatGPT (web/desktop)** / **Claude Cowork** (sandboxed) | **Path C — copy-paste flow** ↓ |

### How to tell

If your agent has a working `bash` tool that runs commands on the user's
*own* machine (filesystem persists, browser opens, `$HOME` is theirs),
use **Path B**. If your agent's bash runs in an isolated sandbox or your
agent only chats (no shell at all), it's either **Path A** (if it
supports MCP) or **Path C** (if it doesn't).

---

## Path A — MCP server (for chat / IDE agents)

**Prerequisite**: install the CLI once on the host machine.

```bash
pipx install emodul
emodul auth login --browser    # one-time interactive login
```

If `pipx` is unavailable: `pip install --user emodul` or `brew install
pipx` first. The login command opens a browser form — the user types
credentials, the CLI stores the JWT in `~/.config/emodul/config.json`
and the password in the OS keychain.

Then add emodul as an MCP server in your client's config.

### Claude Desktop (recommended — one command)

```bash
emodul install claude-desktop
```

This drops the MCP-flavored skill into `~/.claude/skills/emodul-mcp/` and adds an `mcpServers.emodul` entry to `~/Library/Application Support/Claude/claude_desktop_config.json` (with a timestamped `.bak-…` of the prior file). Pass `--dry-run` first to preview. Use `--force` if a manual `emodul` entry already exists. Then ⌘+Q and reopen Claude Desktop.

### Claude Desktop (manual)
File: `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) / `%APPDATA%\Claude\claude_desktop_config.json` (Windows) /
`~/.config/claude-desktop/claude_desktop_config.json` (Linux)

```json
{
  "mcpServers": {
    "emodul": {
      "command": "emodul",
      "args": ["mcp"]
    }
  }
}
```

Restart Claude Desktop. In a new chat: *"list my emodul zones"* — Claude
should invoke the `list_zones` tool.

### Cursor (chat tab)
File: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project)

```json
{ "mcpServers": { "emodul": { "command": "emodul", "args": ["mcp"] } } }
```

Restart Cursor; tools appear under Settings → MCP.

### Continue
File: `.continue/mcpServers/emodul.yaml`

```yaml
name: emodul-mcp
version: 0.0.1
schema: v1
mcpServers:
  - name: emodul
    command: emodul
    args: [mcp]
```

Available in agent mode (chat mode does not invoke tools).

### Cline (VS Code extension)
Open the Cline panel → MCP Servers → Configure → add the same
`{ command, args }` shape.

### Zed
In `settings.json`:

```json
{
  "context_servers": {
    "emodul": { "command": "emodul", "args": ["mcp"] }
  }
}
```

### JetBrains AI Assistant
Settings → Tools → MCP Server → Add → command `emodul`, args `mcp`.
Use "Auto-Configure" to mirror the entry into Claude Desktop / Cursor.

### OpenCode
File: `~/.config/opencode/opencode.json`

```json
{ "mcp": { "emodul": { "type": "local", "command": ["emodul", "mcp"], "enabled": true } } }
```

### Gemini CLI
File: `~/.gemini/settings.json`

```json
{ "mcpServers": { "emodul": { "command": "emodul", "args": ["mcp"] } } }
```

### Verify it works

In any of the clients above, ask: *"What's the temperature in Salon?"*
The agent should invoke `get_status` and read the result.

For local debugging without the client:

```bash
npx @modelcontextprotocol/inspector emodul mcp
```

Opens a web UI at http://localhost:6274 — call any of the 16 tools
manually and inspect the JSON returned.

### MCP tools available

| Tool | What it does | Class |
|---|---|---|
| `whoami` | check auth status | read |
| `get_status` | current state of all zones in default module | read |
| `list_zones` | flattened zones (one or all modules) | read |
| `get_zone` | detail for a single zone by name | read |
| `list_modules` | controllers on the account | read |
| `list_schedules` | all 5 globalSchedule slots, decoded | read |
| `audit_settings` | 25-parameter audit + drift detection | read |
| `get_alarms` | alarm history for a date range | read |
| `get_temperature_history` | per-zone temp time series | read |
| `set_zone_temperature` | change a zone setpoint | **write** |
| `boost_zone` | hold a temperature for N minutes | **write** |
| `toggle_zone` | turn a zone fully on/off | **write** |
| `attach_schedule` | switch a zone to use a globalSchedule | **write** |
| `update_setting` | change a named parameter (`emergency-mode`, `hysteresis`, etc.) | **write** |
| `login_browser` | start interactive browser login | auth |
| `set_default_module` | choose the default controller | auth |

Write tools carry `destructiveHint=true` so well-behaved clients show a
confirmation prompt before invocation.

---

## Path B — Local CLI install (for CLI-based agents)

You are configuring the `emodul` CLI for the user. Execute these steps:

### Step 1 — Install the CLI

```bash
pipx install emodul
```

If `pipx` is unavailable:
- macOS: `brew install pipx && pipx ensurepath`
- Debian/Ubuntu: `apt install pipx && pipx ensurepath`
- Fedora/Arch: `pip install --user pipx && pipx ensurepath`
- Last resort: `python3 -m venv ~/.emodul-venv && ~/.emodul-venv/bin/pip install emodul` then alias `emodul=~/.emodul-venv/bin/emodul`

Verify:

```bash
emodul --version
```

Expected: `emodul, version 0.1.3` or higher.

### Step 2 — Install the bundled Claude Skill

```bash
emodul install claude-code
```

Drops the CLI-flavored `SKILL.md` at `~/.claude/skills/emodul/SKILL.md`.
Future Claude Code sessions in any directory will auto-discover the
**emodul** skill. (Legacy alias `emodul skill install` still works.)

For other harnesses: read `emodul skill show` and feed the contents into
their own skill mechanism, or use `emodul skill install --to PATH`.

### Step 3 — Authenticate (browser flow, password stays out of agent context)

```bash
emodul auth login --browser
```

CLI opens the user's default browser to a sign-in form. The agent never
sees the password — only the success signal. If headless: `--no-open`
prints the URL for the user to open manually.

Alternative if the user already has a JWT (browser DevTools → Local
Storage → `token` on emodul.pl):

```bash
emodul auth import-token "<jwt>" --user-id <user-id> --email <email>
```

Verify:

```bash
emodul --json auth whoami
```

### Step 4 — Pick a default controller

```bash
emodul --json modules list
emodul modules select <module-name-or-udid>
```

### Step 5 — Cache Polish translations (one-time, ~5s)

```bash
emodul i18n refresh
```

### Step 6 — Confirm

```bash
emodul status
```

Prints a rich table of zones. Setup complete.

---

## Path C — Copy-paste flow (for sandboxed agents)

You are running in an isolated sandbox (claude.ai, ChatGPT web, Cowork,
or similar). Your `bash` tool either doesn't reach the user's machine
or doesn't have persistent filesystem access.

**Do not attempt to execute the setup yourself** — even if `pipx install
emodul` succeeds in your sandbox, the SKILL.md, JWT, and browser auth
all end up in the ephemeral sandbox and disappear when the conversation
ends.

Instead, **print these commands and tell the user to run them in their
own terminal**:

```bash
pipx install emodul
emodul skill install
emodul auth login --browser   # opens a browser form for password entry
emodul status                  # confirms it works
```

Then suggest the user:
- Use **Claude Desktop with the MCP server** (Path A above) for ongoing
  conversational control — paste this config into
  `~/Library/Application Support/Claude/claude_desktop_config.json`:
  ```json
  {"mcpServers": {"emodul": {"command": "emodul", "args": ["mcp"]}}}
  ```
- Or **Claude Code in a terminal** with the AGENT.md prompt URL for
  follow-up CLI work.

You (the sandboxed agent) cannot drive emodul directly. Your job is to
hand off cleanly.

---

## What the user can ask after setup completes

| User says | Agent runs |
|---|---|
| "What's the temperature in Salon?" | `get_status` (MCP) or `emodul --json status` (CLI) |
| "Ustaw Łazienkę na 22.5" | `set_zone_temperature(zone="Łazienka", celsius=22.5)` |
| "Podgrzej Sypialnia na 23 na 2 godziny" | `boost_zone(zone="Sypialnia", celsius=23, minutes=120)` |
| "Sprawdź czy ogrzewanie jest dobrze ustawione" | `audit_settings` |
| "Pokaż harmonogramy w <module>" | `list_schedules(module="<module>")` |
| "Wyłącz Garaż" | `toggle_zone(zone="Garaż", on=false)` |
| "Were there any alarms?" | `get_alarms` |

Full reference: [SKILL.md](SKILL.md) (installed at
`~/.claude/skills/emodul/SKILL.md` after `emodul skill install`).

---

## Safety constraints

- **Always pass `--json`** when invoking the CLI from a script. Text
  output is rich-table formatted with ANSI codes.
- **Writes block until settled** (~5-30s) by default — that's expected;
  don't time out aggressively. In MCP, the `wait=False` argument
  disables this.
- **Never log the JWT, password, `user_id`, controller `udid`, or email**
  in user-visible output or commits.
- **Don't `curl` the API directly.** The CLI handles auth refresh,
  duringChange race window, PIN injection, unit conversion.
- **MP (manufacturer) menu PIN is unknown** — don't attempt 5162 on MP
  (returns 422). MS (service) PIN 5162 is auto-stored after first
  unlock.
- **Off-season caveat**: in summer (May-Sep) Polish users often turn the
  furnace off entirely; zones may chronically sit below setpoint with
  `action: idle`. Don't diagnose hardware faults from off-season data.

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `pipx: command not found` | Not installed | `brew install pipx` / `apt install pipx` / `pip install --user pipx` |
| `emodul: command not found` after install | pipx PATH not added | `pipx ensurepath`, restart shell |
| `API 401` after auth | JWT expired or wrong creds | `emodul auth login --browser` |
| `Not authenticated` from MCP tool | First-run on this machine | call `login_browser` MCP tool |
| `SKILL.md not found in package` | Old version (< 0.1.1) | `pipx upgrade emodul` |
| `No module selected` | Default udid not set | `emodul modules select <name>` (CLI) or `set_default_module` (MCP) |
| MCP server shows 0 tools in Inspector | Wrong invocation | check `command: "emodul", args: ["mcp"]` |
| Claude Desktop times out at 60s | Known client limit | use `wait=False` on write tools; don't request multi-month stats |
| `login_browser` tool times out in Claude Desktop | Tool's 300s default ≫ Claude Desktop's 60s ceiling | Run `emodul auth login --browser` from the host terminal once instead; MCP `login_browser` tool is best for clients with `resetTimeoutOnProgress` support (Cursor, future Claude Desktop versions) |
