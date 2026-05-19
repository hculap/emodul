"""`emodul install` and `emodul uninstall` — wire emodul into AI clients.

One command, two targets:

- **claude-code** — drops the CLI-flavored `SKILL.md` into
  `~/.claude/skills/emodul/`. Claude Code auto-discovers it on next session.
- **claude-desktop** — drops the MCP-flavored `SKILL_MCP.md` into
  `~/.claude/skills/emodul-mcp/` AND adds an `mcpServers.emodul` entry to
  `claude_desktop_config.json` (atomic write with timestamped backup).

The two skill folders coexist with different `name:` slugs, so both clients
see both skills and pick the right one based on `description:` keyword match.

`--all` fans out to both targets. `--dry-run` previews without writing.
`--force` is required to overwrite an existing `mcpServers.emodul` whose
arguments differ from what we'd write (e.g. user manually edited the path).
"""
from __future__ import annotations

import difflib
import importlib.resources
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import click

from emodul._client_paths import (
    SUPPORTED_CLIENTS,
    claude_desktop_config_path,
    claude_skills_dir,
    detect_clients,
)
from emodul._config_writer import (
    ConfigWriteError,
    load_config,
    merge_mcp_server,
    remove_mcp_server,
    write_with_backup,
)
from emodul.format import console, dump_json, err_console


def _bundled(name: str) -> Path:
    """Resolve a bundled file (SKILL.md / SKILL_MCP.md) inside the package,
    with editable-install fallback to repo root.
    """
    in_pkg = Path(str(importlib.resources.files("emodul").joinpath(name)))
    if in_pkg.exists():
        return in_pkg
    dev = Path(__file__).resolve().parent.parent.parent / name
    return dev if dev.exists() else in_pkg


def _emodul_binary() -> str:
    """Path to write into `command:` for the MCP server entry.

    Order of preference:
    1. `emodul` on PATH (typical after `pipx install emodul`).
    2. `sys.argv[0]` if absolute (the running script's location).
    3. `<sys.executable's dir>/emodul` (venv neighbor).
    """
    found = shutil.which("emodul")
    if found:
        return found
    if sys.argv and Path(sys.argv[0]).is_absolute():
        candidate = Path(sys.argv[0])
        if candidate.exists():
            return str(candidate)
    neighbor = Path(sys.executable).parent / "emodul"
    return str(neighbor)


def _mcp_entry() -> dict[str, Any]:
    """Canonical mcpServers.emodul value."""
    return {"command": _emodul_binary(), "args": ["mcp"]}


# ---------- claude-code target ----------

def _cc_skill_target() -> Path:
    return claude_skills_dir() / "emodul" / "SKILL.md"


def _install_claude_code(*, dry_run: bool, force: bool) -> dict[str, Any]:
    src = _bundled("SKILL.md")
    if not src.exists():
        return {
            "ok": False,
            "target": "claude-code",
            "error": f"Bundled SKILL.md not found at {src}. Reinstall emodul.",
        }
    dst = _cc_skill_target()
    action: str
    if dst.exists() or dst.is_symlink():
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            action = "unchanged"
        elif not force:
            return {
                "ok": False,
                "target": "claude-code",
                "error": (
                    f"{dst} already exists with different content. "
                    "Pass --force to overwrite."
                ),
                "code": "conflict",
            }
        else:
            action = "updated"
    else:
        action = "added"

    if dry_run:
        return {
            "ok": True,
            "target": "claude-code",
            "dry_run": True,
            "action": action,
            "path": str(dst),
        }
    if action != "unchanged":
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.copy2(src, dst)
    return {
        "ok": True,
        "target": "claude-code",
        "action": action,
        "path": str(dst),
    }


def _uninstall_claude_code(*, dry_run: bool) -> dict[str, Any]:
    dst = _cc_skill_target()
    if not (dst.exists() or dst.is_symlink()):
        return {"ok": True, "target": "claude-code", "action": "absent", "path": str(dst)}
    if dry_run:
        return {"ok": True, "target": "claude-code", "dry_run": True, "action": "removed", "path": str(dst)}
    dst.unlink()
    return {"ok": True, "target": "claude-code", "action": "removed", "path": str(dst)}


# ---------- claude-desktop target ----------

def _cd_skill_target() -> Path:
    return claude_skills_dir() / "emodul-mcp" / "SKILL.md"


def _install_claude_desktop(*, dry_run: bool, force: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"target": "claude-desktop", "ok": True, "steps": []}

    # Step 1: drop SKILL_MCP.md into ~/.claude/skills/emodul-mcp/SKILL.md
    src = _bundled("SKILL_MCP.md")
    if not src.exists():
        return {
            "ok": False,
            "target": "claude-desktop",
            "error": f"Bundled SKILL_MCP.md not found at {src}. Reinstall emodul.",
        }
    dst = _cd_skill_target()
    if dst.exists() or dst.is_symlink():
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            skill_action = "unchanged"
        elif not force:
            return {
                "ok": False,
                "target": "claude-desktop",
                "error": (
                    f"{dst} already exists with different content. "
                    "Pass --force to overwrite."
                ),
                "code": "conflict",
            }
        else:
            skill_action = "updated"
    else:
        skill_action = "added"
    if not dry_run and skill_action != "unchanged":
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.copy2(src, dst)
    result["steps"].append({
        "kind": "skill",
        "action": skill_action,
        "path": str(dst),
    })

    # Step 2: merge mcpServers.emodul into claude_desktop_config.json
    cfg_path = claude_desktop_config_path()
    try:
        existing = load_config(cfg_path)
    except ConfigWriteError as exc:
        return {
            "ok": False,
            "target": "claude-desktop",
            "error": str(exc),
            "code": "config_unreadable",
        }
    entry = _mcp_entry()
    new_cfg, mcp_action = merge_mcp_server(existing, "emodul", entry, force=force)
    if mcp_action == "conflict":
        diff = _config_diff(existing, new_cfg)
        return {
            "ok": False,
            "target": "claude-desktop",
            "error": (
                f"mcpServers.emodul already exists in {cfg_path} with different "
                "arguments. Re-run with --force to replace it."
            ),
            "code": "conflict",
            "diff": diff,
            "existing": existing.get("mcpServers", {}).get("emodul"),
            "would_write": entry,
        }

    backup: Path | None = None
    if not dry_run and mcp_action != "unchanged":
        try:
            backup = write_with_backup(cfg_path, new_cfg)
        except OSError as exc:
            return {
                "ok": False,
                "target": "claude-desktop",
                "error": f"Failed to write {cfg_path}: {exc}",
                "code": "write_failed",
            }

    result["steps"].append({
        "kind": "mcp_config",
        "action": mcp_action,
        "path": str(cfg_path),
        "backup": str(backup) if backup else None,
        "entry": entry,
    })
    if dry_run:
        result["dry_run"] = True
    return result


def _uninstall_claude_desktop(*, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"target": "claude-desktop", "ok": True, "steps": []}

    # Remove skill file
    dst = _cd_skill_target()
    if dst.exists() or dst.is_symlink():
        if not dry_run:
            dst.unlink()
        result["steps"].append({"kind": "skill", "action": "removed", "path": str(dst)})
    else:
        result["steps"].append({"kind": "skill", "action": "absent", "path": str(dst)})

    # Remove mcpServers.emodul
    cfg_path = claude_desktop_config_path()
    if not cfg_path.exists():
        result["steps"].append({
            "kind": "mcp_config", "action": "absent", "path": str(cfg_path),
        })
        if dry_run:
            result["dry_run"] = True
        return result
    try:
        existing = load_config(cfg_path)
    except ConfigWriteError as exc:
        return {
            "ok": False,
            "target": "claude-desktop",
            "error": str(exc),
            "code": "config_unreadable",
        }
    new_cfg, removed = remove_mcp_server(existing, "emodul")
    if not removed:
        result["steps"].append({
            "kind": "mcp_config", "action": "absent", "path": str(cfg_path),
        })
    else:
        backup: Path | None = None
        if not dry_run:
            try:
                backup = write_with_backup(cfg_path, new_cfg)
            except OSError as exc:
                return {
                    "ok": False,
                    "target": "claude-desktop",
                    "error": f"Failed to write {cfg_path}: {exc}",
                    "code": "write_failed",
                }
        result["steps"].append({
            "kind": "mcp_config",
            "action": "removed",
            "path": str(cfg_path),
            "backup": str(backup) if backup else None,
        })
    if dry_run:
        result["dry_run"] = True
    return result


def _config_diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    b = json.dumps(before, indent=2, ensure_ascii=False).splitlines()
    a = json.dumps(after, indent=2, ensure_ascii=False).splitlines()
    return list(difflib.unified_diff(b, a, fromfile="before", tofile="after", n=2))


# ---------- pretty printing ----------

_ACTION_STYLE = {
    "added": "green",
    "updated": "yellow",
    "removed": "yellow",
    "unchanged": "dim",
    "absent": "dim",
}


def _print_result(payload: dict[str, Any]) -> None:
    if not payload["ok"]:
        err_console.print(f"[red]✗[/red] {payload.get('target')}: {payload.get('error')}")
        if payload.get("diff"):
            for line in payload["diff"]:
                err_console.print(line)
        return
    target = payload["target"]
    dry = payload.get("dry_run")
    prefix = "[blue]would[/blue]" if dry else "[green]✓[/green]"
    if target == "claude-code":
        console.print(f"{prefix} {target}: {payload['action']} {payload['path']}")
    else:
        for step in payload["steps"]:
            action = step["action"]
            style = _ACTION_STYLE.get(action, "white")
            console.print(
                f"{prefix} {target}/{step['kind']}: "
                f"[{style}]{action}[/{style}] {step['path']}"
            )
            if step.get("backup"):
                console.print(f"  [dim]backup: {step['backup']}[/dim]")


# ---------- click registration ----------

_TARGET_HANDLERS = {
    "claude-code": (_install_claude_code, _uninstall_claude_code),
    "claude-desktop": (_install_claude_desktop, _uninstall_claude_desktop),
}


def register(cli: click.Group, wrap) -> None:
    @cli.command("install")
    @click.argument(
        "target",
        type=click.Choice(list(SUPPORTED_CLIENTS)),
        required=False,
    )
    @click.option("--all", "do_all", is_flag=True, help="Install for every detected client.")
    @click.option("--dry-run", is_flag=True, help="Preview without writing files.")
    @click.option(
        "--force",
        is_flag=True,
        help="Overwrite existing skill files or mcpServers.emodul entry whose contents differ.",
    )
    @click.pass_obj
    def install(ctx, target: str | None, do_all: bool, dry_run: bool, force: bool) -> None:
        """Install emodul into an AI client (skill + MCP config as appropriate).

        Targets:

        \b
          claude-code     CLI-flavored skill → ~/.claude/skills/emodul/SKILL.md
          claude-desktop  MCP-flavored skill → ~/.claude/skills/emodul-mcp/SKILL.md
                          AND mcpServers.emodul → claude_desktop_config.json

        Examples:

        \b
          emodul install claude-code
          emodul install claude-desktop
          emodul install --all
          emodul install claude-desktop --dry-run
          emodul install claude-desktop --force  # overwrite existing entry
        """
        if not target and not do_all:
            click.echo(install.get_help(click.get_current_context()))
            return

        if do_all:
            detected = detect_clients()
            targets = [t for t in SUPPORTED_CLIENTS if detected[t]]
            if not targets:
                err_console.print(
                    "[yellow]No supported AI clients detected.[/yellow] "
                    "Pass a target explicitly or install Claude Code / Claude Desktop first."
                )
                sys.exit(1)
        else:
            assert target is not None
            targets = [target]

        results = []
        any_failed = False
        for t in targets:
            handler = _TARGET_HANDLERS[t][0]
            payload = handler(dry_run=dry_run, force=force)
            results.append(payload)
            if not payload["ok"]:
                any_failed = True

        if ctx.json:
            dump_json(results if do_all else results[0])
        else:
            for r in results:
                _print_result(r)
            if not dry_run and any(
                r["ok"] and r.get("target") == "claude-desktop"
                for r in results
            ):
                console.print(
                    "\n[dim]Quit and reopen Claude Desktop (⌘+Q on macOS) to load.[/dim]"
                )

        if any_failed:
            sys.exit(1)

    @cli.command("uninstall")
    @click.argument(
        "target",
        type=click.Choice(list(SUPPORTED_CLIENTS)),
        required=False,
    )
    @click.option("--all", "do_all", is_flag=True, help="Uninstall from every detected client.")
    @click.option("--dry-run", is_flag=True, help="Preview without modifying files.")
    @click.pass_obj
    def uninstall(ctx, target: str | None, do_all: bool, dry_run: bool) -> None:
        """Reverse `emodul install` for a target client."""
        if not target and not do_all:
            click.echo(uninstall.get_help(click.get_current_context()))
            return

        if do_all:
            targets = list(SUPPORTED_CLIENTS)
        else:
            assert target is not None
            targets = [target]

        results = []
        any_failed = False
        for t in targets:
            handler = _TARGET_HANDLERS[t][1]
            payload = handler(dry_run=dry_run)
            results.append(payload)
            if not payload["ok"]:
                any_failed = True

        if ctx.json:
            dump_json(results if do_all else results[0])
        else:
            for r in results:
                _print_result(r)

        if any_failed:
            sys.exit(1)
