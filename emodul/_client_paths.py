"""Resolve install paths for supported AI clients + detect what's installed.

`emodul install` writes files into well-known locations:
- **Claude Code** reads `~/.claude/skills/<name>/SKILL.md` (folder per skill).
  Claude Desktop reads the same dir, so both clients pick up file-based skills.
- **Claude Desktop** also reads `mcpServers` from a per-platform config JSON.

Detection is best-effort: we look for marker paths Anthropic creates the first
time a client runs. False negatives (we say "not installed" when it is) are
fine — the user can pass the target explicitly. False positives are worse, so
we only flag a client as detected when its config file or settings dir exists.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path


def claude_skills_dir() -> Path:
    """`~/.claude/skills/` — shared by Claude Code and Claude Desktop."""
    return Path.home() / ".claude" / "skills"


def claude_desktop_config_path() -> Path:
    """Per-platform config that Claude Desktop reads at startup for MCP servers."""
    system = platform.system()
    if system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    # Linux is unofficial for Claude Desktop; mirror Anthropic's XDG-style layout.
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def detect_clients() -> dict[str, bool]:
    """Return `{client_id: bool}` based on marker-path existence.

    - `claude-code`: detected if `~/.claude/` exists (CC creates it on first run).
    - `claude-desktop`: detected if the per-platform config file OR its parent
      directory exists. Parent-only counts because a freshly-installed CD that
      has never written its config still has the dir.
    """
    cd_config = claude_desktop_config_path()
    return {
        "claude-code": (Path.home() / ".claude").exists(),
        "claude-desktop": cd_config.exists() or cd_config.parent.exists(),
    }


SUPPORTED_CLIENTS = ("claude-code", "claude-desktop")
