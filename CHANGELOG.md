# Changelog

All notable changes to `emodul` are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions match the
[PyPI releases](https://pypi.org/project/emodul/#history) and
[GitHub Releases](https://github.com/hculap/emodul/releases).

## [0.1.10] — 2026-05-21

### Changed
- `get_temperature_history` (MCP tool) now bucket-averages each zone's series
  to at most 600 samples so multi-day fetches across all zones fit under
  Claude Desktop's ~1 MB / 25k-token tool-result cap. A 7-day fetch across
  8 zones drops from ~2.6 MB raw to ~150 KB after bucketing — enough
  resolution for a chart, comfortably under every known client cap.
- Response gains a `downsample` envelope (`{downsampled, max_points_per_zone,
  per_zone: {<key>: {original, returned}}}`) so the agent can report the
  pre-bucket sample count to the user. The `{x, y}` shape and series keys
  are unchanged.
- CLI `emodul stats linear` is unaffected — downsampling lives only in the
  MCP tool. The Python SDK's FastMCP has no server-side response cap to
  configure; the 1 MB ceiling lives in Anthropic clients.

## [0.1.9] — 2026-05-19

### Changed
- `logout` (MCP tool and `emodul auth logout` CLI) now returns a precise
  `keychain_status` field so callers can distinguish:
  - `skipped` — `clear_keychain` was False
  - `no_email` — requested but config has no email to look up
  - `not_found` — email valid, no keychain entry (often: already removed)
  - `deleted` — entry existed and was removed
  - `error` — `delete_password` raised
  Each failure case includes a manual-recovery hint
  (`security find-generic-password -s emodul`).
- `emodul auth logout --clear-keychain` now does in one command what
  previously required `auth logout` followed by `auth forget-password`.
  `forget-password` stays for backward compat.

## [0.1.8] — 2026-05-19

### Added
- New MCP tool `logout(clear_keychain=False)` — clears the stored token
  and (optionally) deletes the OS-keychain password. `destructiveHint=true`
  so chat clients prompt for confirmation. Server `instructions` now list
  `logout` under AUTH tools (17 tools: 9 read + 5 write + 3 auth).

## [0.1.7] — 2026-05-19

### Fixed
- **Critical**: the HTML login form (`emodul auth login --browser` and the
  MCP `login_browser` tool) was sending `multipart/form-data`, but the
  local Python server only parsed `application/x-www-form-urlencoded` via
  `parse_qs` — every submit came back with empty email + password and the
  server returned **400 "Email and password are required."**
  Broken in 0.1.2 through 0.1.6; the bug was hidden because demo
  recordings used the CLI terminal path and the MCP tool always timed out
  before users could click Submit. JS submit handler now wraps `FormData`
  in `URLSearchParams` so fetch sends the right Content-Type.

## [0.1.6] — 2026-05-19

### Changed
- `login_browser` MCP tool defaults to `wait=False`. In chat clients
  (Claude Desktop / Cursor chat / Continue / Cline / Zed) the previous
  blocking call always timed out at the ~60s tool ceiling before the user
  could submit the form. Now the tool binds the local server, returns the
  URL in <1s, and persists the token + keychain entry in the background.
  Agent then polls `whoami` to detect completion.
- `wait=True` is still available for CLI/IDE agents that support
  long-running tool calls (Claude Code, Codex CLI).
- `web_auth.web_login_flow` refactored into `start_login_server` +
  `wait_for_login` + `cancel_login`; existing API preserved as a
  composition wrapper for the terminal CLI.

## [0.1.5] — 2026-05-19

### Changed
- Expanded the MCP server `instructions` field (returned in
  `InitializeResult`) from one sentence to ~365 words covering
  when-to-use triggers (English + Polish), 16-tool roster grouped by
  class, recommended workflow, conventions, result envelope semantics,
  and safety rules. Per the MCP spec, clients inject this into the LLM's
  system prompt on every turn — the standard mechanism for delivering
  skill-like persistent context to clients that don't read
  `~/.claude/skills/` (Claude Desktop, Cursor chat, Continue, Cline, Zed).

## [0.1.4] — 2026-05-19

### Added
- `emodul install <target>` and `emodul uninstall <target>` for
  one-command setup of AI clients:
  - `claude-code` drops the CLI-flavored `SKILL.md` into
    `~/.claude/skills/emodul/`
  - `claude-desktop` drops the MCP-flavored `SKILL_MCP.md` into
    `~/.claude/skills/emodul-mcp/` AND merges `mcpServers.emodul` into
    `claude_desktop_config.json` (atomic write with timestamped backup,
    keep last 5)
  - `--all` fans out to detected clients
  - `--dry-run` previews
  - `--force` overwrites an existing `mcpServers.emodul` entry whose
    arguments differ
- `emodul/_client_paths.py` — per-platform config paths + client detection
- `emodul/_config_writer.py` — atomic JSON merge: tempfile + `os.replace`,
  strict JSON parse (fail-loud on comments), `fcntl.flock` for
  serialization, shallow-merge preserving sibling top-level keys
- `SKILL_MCP.md` — new MCP-flavored skill (16-tool inventory,
  `{ok: false}` envelope semantics, no shell examples)

The two skill folders coexist (different `name:` YAML slugs) so each
client picks the right one via description-keyword matching. Backward
compat: `emodul skill install` / `emodul skill uninstall` keep working.

## [0.1.3] — 2026-05-19

### Added
- **Bundled MCP server** (`emodul mcp`) exposing 16 tools:
  9 read (`whoami`, `list_modules`, `get_status`, `list_zones`, `get_zone`,
  `list_schedules`, `audit_settings`, `get_alarms`, `get_temperature_history`),
  5 write (`set_zone_temperature`, `boost_zone`, `toggle_zone`,
  `attach_schedule`, `update_setting`), 2 auth (`login_browser`,
  `set_default_module`). Use from Claude Desktop, Cursor chat, Continue,
  Cline, Zed, or JetBrains AI Assistant via stdio MCP transport.
- 3-path `AGENT.md` restructure: MCP server / CLI-agent prompt /
  sandboxed fallback.
- Browser-based login (`emodul auth login --browser`) — local
  127.0.0.1 form so AI agents never see the password.

### Changed
- Python floor lowered 3.11 → 3.10. Unblocks Cowork sandboxes and
  Ubuntu 22.04 LTS.

### Fixed
- `web_auth.web_login_flow` raises `LoginFlowError` (subclass of
  `Exception`) instead of `SystemExit` so the MCP server's `@safely`
  decorator catches it cleanly. Previously the MCP server process died
  on any login timeout / bind failure / cancel.

## [0.1.2] — 2026-05-18

### Added
- Browser-based login flow (`emodul auth login --browser`) — opens a
  local form so AI agents driving the CLI never see the password.

## [0.1.1] — 2026-05-18

### Added
- `SKILL.md` bundled in the wheel via `force-include`; new
  `emodul skill install` / `uninstall` / `show` / `path` commands so
  Claude Code auto-discovers the skill after `pipx install emodul`.

## [0.1.0] — 2026-05-17

Initial release. CLI with 12 subcommand groups (`auth`, `modules`,
`zones`, `menu`, `stats`, `alarms`, `tiles`, `settings`, `schedules`,
`watch`, `skill`, `raw`). JWT auth with keychain-backed auto-refresh,
named-slug parameter control, Polish menu decoding via i18n cache,
SQLite-backed background watcher with launchd/systemd installer.

[0.1.9]: https://github.com/hculap/emodul/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/hculap/emodul/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/hculap/emodul/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/hculap/emodul/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/hculap/emodul/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/hculap/emodul/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/hculap/emodul/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/hculap/emodul/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/hculap/emodul/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/hculap/emodul/releases/tag/v0.1.0
