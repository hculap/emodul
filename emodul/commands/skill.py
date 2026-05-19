"""`emodul skill ...` — install / show / path the bundled Claude Skill.

After `pip install emodul`, the SKILL.md from the repo ships inside the
package (see `[tool.hatch.build.targets.wheel.force-include]` in pyproject).
These commands make it trivial for an AI agent to discover and install:

    pipx install emodul
    emodul skill install        # → ~/.claude/skills/emodul/SKILL.md
"""
from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path

import click

from emodul.format import console, dump_json


def _bundled_skill_path() -> Path:
    """Resolve SKILL.md location.

    Real install: `emodul/SKILL.md` inside site-packages (force-include in
    pyproject puts it there).
    Editable install (`pip install -e .`): force-include doesn't touch the
    source tree, so fall back to repo root.
    """
    in_package = Path(str(importlib.resources.files("emodul").joinpath("SKILL.md")))
    if in_package.exists():
        return in_package
    # Editable / dev fallback: emodul/commands/skill.py → repo_root/SKILL.md
    dev_fallback = Path(__file__).resolve().parent.parent.parent / "SKILL.md"
    return dev_fallback if dev_fallback.exists() else in_package


def _default_install_target() -> Path:
    """Where Claude Code discovers user-level skills."""
    return Path.home() / ".claude" / "skills" / "emodul" / "SKILL.md"


def _ensure_bundled() -> Path:
    p = _bundled_skill_path()
    if not p.exists():
        raise SystemExit(
            f"SKILL.md not found at {p}.\n"
            "This package may have been built without the bundled skill — "
            "reinstall the latest version: `pipx upgrade emodul` or "
            "`pip install --upgrade emodul`."
        )
    return p


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def skill() -> None:
        """Manage the bundled Claude Skill (SKILL.md)."""

    @skill.command("path")
    def path_() -> None:
        """Print the absolute path of the SKILL.md shipped with this package."""
        click.echo(str(_ensure_bundled()))

    @skill.command("show")
    def show() -> None:
        """Print SKILL.md contents to stdout."""
        click.echo(_ensure_bundled().read_text(encoding="utf-8"))

    @skill.command("install")
    @click.option(
        "--to",
        "target",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Custom install target. Default: ~/.claude/skills/emodul/SKILL.md",
    )
    @click.option(
        "--symlink/--copy",
        "use_symlink",
        default=False,
        show_default=True,
        help="Symlink (live updates on package upgrade) or copy (frozen snapshot).",
    )
    @click.option("--force", is_flag=True, help="Overwrite an existing file at target.")
    @click.pass_obj
    def install(ctx, target: Path | None, use_symlink: bool, force: bool) -> None:
        """Install SKILL.md into Claude Code's user-level skills directory.

        After installation, Claude Code in any directory automatically
        discovers the `emodul` skill and uses this CLI on heating-related
        user requests.

        Idempotent unless target file already exists (use --force).
        """
        src = _ensure_bundled()
        dst = target or _default_install_target()
        dst.parent.mkdir(parents=True, exist_ok=True)

        already_present = dst.exists() or dst.is_symlink()
        if already_present and not force:
            raise SystemExit(
                f"{dst} already exists. Pass --force to overwrite, or "
                f"`emodul skill uninstall` first."
            )
        if already_present:
            dst.unlink()

        if use_symlink:
            dst.symlink_to(src)
            method = "symlink"
        else:
            shutil.copy2(src, dst)
            method = "copy"

        if ctx.json:
            dump_json(
                {
                    "installed_to": str(dst),
                    "source": str(src),
                    "method": method,
                }
            )
        else:
            console.print(f"[green]✓[/green] Installed SKILL.md → {dst} ({method})")
            console.print(
                "  Claude Code in any future session will auto-discover the "
                "[bold]emodul[/bold] skill."
            )

    @skill.command("uninstall")
    @click.option(
        "--from",
        "target",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Custom path (default: ~/.claude/skills/emodul/SKILL.md).",
    )
    @click.pass_obj
    def uninstall(ctx, target: Path | None) -> None:
        """Remove the installed SKILL.md from Claude Code's skills directory."""
        dst = target or _default_install_target()
        if not dst.exists() and not dst.is_symlink():
            msg = f"Nothing to remove at {dst}"
            if ctx.json:
                dump_json({"removed": False, "path": str(dst), "message": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            return
        dst.unlink()
        if ctx.json:
            dump_json({"removed": True, "path": str(dst)})
        else:
            console.print(f"[green]✓[/green] Removed {dst}")
