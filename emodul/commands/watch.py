"""`emodul watch ...` — background poller that records relay/zone transitions.

Stores events in a SQLite database. Cross-platform: ships installers for
macOS (launchd) and Linux (systemd --user) so it survives reboots.
"""
from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from emodul import i18n as i18n_mod
from emodul import storage
from emodul.format import console, dump_json, err_console, flatten_zones

SERVICE_NAME_MACOS = "com.emodul.watcher"
SERVICE_NAME_LINUX = "emodul-watcher"


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def watch() -> None:
        """Background watcher: log relay and zone transitions to SQLite."""

    @watch.command("run")
    @click.option("--interval", type=int, default=60, show_default=True, help="Poll seconds.")
    @click.option("--db", type=click.Path(dir_okay=False), default=None, help="SQLite path.")
    @click.option(
        "-m",
        "--module",
        "udid_args",
        multiple=True,
        help="Limit to this module (repeat for multiple). Default: all.",
    )
    @click.option(
        "--once", is_flag=True, help="Single poll then exit (for testing/cron use)."
    )
    @click.pass_obj
    @wrap
    def run(
        ctx,
        interval: int,
        db: str | None,
        udid_args: tuple[str, ...],
        once: bool,
    ) -> None:
        """Foreground polling loop. SIGTERM = clean exit."""
        ctx.config.require_auth()
        db_path = Path(db) if db else storage.default_db_path()
        conn = storage.open_db(db_path)
        err_console.print(f"[dim]emodul-watcher → {db_path} (interval={interval}s)[/dim]")

        stop = {"flag": False}

        def _handle_sig(signum, _frame):
            stop["flag"] = True
            err_console.print(f"[yellow]signal {signum} → finishing[/yellow]")

        signal.signal(signal.SIGTERM, _handle_sig)
        signal.signal(signal.SIGINT, _handle_sig)

        with ctx.api() as api:
            udids: list[str] = list(udid_args) or _all_udids(api)
            dictionary = i18n_mod.load_dictionary(ctx.config.language)
            storage.log(
                conn,
                "info",
                f"watcher started; modules={udids}; interval={interval}s; "
                f"i18n_entries={len(dictionary)}",
                int(time.time()),
            )
            while not stop["flag"]:
                ts = int(time.time())
                for udid in udids:
                    try:
                        snap = api.get_module(udid)
                    except Exception as exc:
                        storage.log(conn, "error", f"{udid}: {exc}", ts)
                        err_console.print(f"[red]{udid}: {exc}[/red]")
                        continue
                    _record_tiles(conn, ts, udid, snap, dictionary)
                    _record_zones(conn, ts, udid, snap)
                if once:
                    break
                # Sleep in small chunks so SIGTERM is responsive.
                for _ in range(interval):
                    if stop["flag"]:
                        break
                    time.sleep(1)
        conn.close()

    @watch.command("status")
    @click.option("--db", type=click.Path(dir_okay=False), default=None)
    @click.option("--limit", type=int, default=20, show_default=True)
    @click.pass_obj
    def status(ctx, db: str | None, limit: int) -> None:
        """Show the latest recorded events + installed service status."""
        db_path = Path(db) if db else storage.default_db_path()
        info = {
            "db": str(db_path),
            "db_exists": db_path.exists(),
            "service": _service_status(),
        }
        if db_path.exists():
            conn = storage.open_db(db_path)
            info["counts"] = {
                "tile_events": conn.execute("SELECT COUNT(*) FROM tile_events").fetchone()[0],
                "zone_events": conn.execute("SELECT COUNT(*) FROM zone_events").fetchone()[0],
                "run_log": conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0],
            }
            info["recent_tile_events"] = [
                {"ts": r[0], "udid": r[1], "tile_id": r[2], "name": r[3], "state": r[4]}
                for r in conn.execute(
                    "SELECT ts, udid, tile_id, name, state "
                    "FROM tile_events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                )
            ]
            info["recent_zone_events"] = [
                {
                    "ts": r[0],
                    "udid": r[1],
                    "zone_id": r[2],
                    "name": r[3],
                    "set_c": r[4],
                    "current_c": r[5],
                    "mode": r[6],
                    "relay": r[7],
                }
                for r in conn.execute(
                    "SELECT ts, udid, zone_id, name, set_c, current_c, mode, relay "
                    "FROM zone_events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                )
            ]
            conn.close()
        dump_json(info)

    @watch.command("install-service")
    @click.option("--interval", type=int, default=60, show_default=True)
    @click.option("--db", type=click.Path(dir_okay=False), default=None)
    @click.pass_obj
    def install(ctx, interval: int, db: str | None) -> None:
        """Install launchd (macOS) or systemd --user (Linux) unit so it survives reboot."""
        db_path = Path(db) if db else storage.default_db_path()
        cmd = _watcher_command(interval, db_path)
        plat = sys.platform
        if plat == "darwin":
            path = _install_launchd(cmd)
            console.print(f"[green]launchd plist installed → {path}[/green]")
            console.print("  Loaded and started. View logs: tail -f /tmp/emodul-watcher.{out,err}.log")
        elif plat.startswith("linux"):
            path = _install_systemd(cmd)
            console.print(f"[green]systemd user unit installed → {path}[/green]")
            console.print(
                "  Started + enabled at login.\n"
                "  To keep running when you're logged out, run once: "
                "[bold]sudo loginctl enable-linger $USER[/bold]"
            )
            console.print("  Logs: journalctl --user -u emodul-watcher -f")
        else:
            raise SystemExit(
                f"Unsupported platform {plat!r}. Run `emodul watch run` from any "
                f"supervisor (cron, supervisord, Windows Task Scheduler, etc.)."
            )

    @watch.command("uninstall-service")
    def uninstall() -> None:
        """Stop and remove the installed service."""
        plat = sys.platform
        if plat == "darwin":
            _uninstall_launchd()
            console.print("[green]launchd plist unloaded and removed.[/green]")
        elif plat.startswith("linux"):
            _uninstall_systemd()
            console.print("[green]systemd user unit stopped and removed.[/green]")
        else:
            raise SystemExit(f"Unsupported platform {plat!r}.")


# ---------------------------------------------------------------- helpers

def _all_udids(api) -> list[str]:
    return [m["udid"] for m in api.list_modules() if m.get("udid")]


def _record_tiles(conn, ts: int, udid: str, snap: dict, dictionary: dict[str, str]) -> None:
    for tile in snap.get("tiles") or []:
        params = tile.get("params") or {}
        if "workingStatus" not in params:
            continue
        state = 1 if params["workingStatus"] else 0
        prev = storage.latest_tile_state(conn, udid, tile["id"])
        if prev != state:
            name = (
                dictionary.get(str(params.get("txtId")))
                or params.get("description")
                or ""
            )
            storage.insert_tile_event(conn, ts, udid, int(tile["id"]), name, state)


def _record_zones(conn, ts: int, udid: str, snap: dict) -> None:
    for row in flatten_zones(snap):
        prev_set, prev_mode_relay = storage.latest_zone_setpoint(conn, udid, row["zone_id"])
        # Compose a "fingerprint" of things we care about transitioning:
        # setpoint, mode, per-zone heating relay state.
        cur_set = row.get("set_c")
        cur_relay = row.get("relay")
        cur_mode = row.get("mode")
        # We re-query latest full row to compare relay too — keep it simple by
        # always inserting when ANY of (set_c, mode, relay) differs from latest.
        latest = conn.execute(
            "SELECT set_c, mode, relay FROM zone_events "
            "WHERE udid=? AND zone_id=? ORDER BY ts DESC LIMIT 1",
            (udid, row["zone_id"]),
        ).fetchone()
        changed = (
            latest is None
            or latest[0] != cur_set
            or latest[1] != cur_mode
            or latest[2] != cur_relay
        )
        if changed:
            storage.insert_zone_event(
                conn,
                ts,
                udid,
                int(row["zone_id"]),
                row.get("name") or "",
                cur_set,
                row.get("current_c"),
                cur_mode,
                cur_relay,
            )


def _watcher_command(interval: int, db_path: Path) -> list[str]:
    """Use `<interpreter> -m emodul watch run` — survives PATH issues."""
    return [
        sys.executable,
        "-m",
        "emodul",
        "watch",
        "run",
        "--interval",
        str(interval),
        "--db",
        str(db_path),
    ]


# ---------- launchd (macOS) ----------

def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_NAME_MACOS}.plist"


def _install_launchd(cmd: list[str]) -> Path:
    log_dir = Path("/tmp")
    plist = _render_plist(cmd, log_dir)
    p = _launchd_plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist, encoding="utf-8")
    # Reload if already loaded; ignore errors.
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    res = subprocess.run(["launchctl", "load", str(p)], capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"launchctl load failed: {res.stderr}")
    return p


def _uninstall_launchd() -> None:
    p = _launchd_plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        p.unlink()


def _render_plist(cmd: list[str], log_dir: Path) -> str:
    args_xml = "\n".join(f"    <string>{_xml_escape(a)}</string>" for a in cmd)
    env_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    home = str(Path.home())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{SERVICE_NAME_MACOS}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>{log_dir}/emodul-watcher.out.log</string>
  <key>StandardErrorPath</key><string>{log_dir}/emodul-watcher.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>{home}</string>
    <key>PATH</key><string>{env_path}</string>
  </dict>
</dict>
</plist>
"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------- systemd --user (Linux) ----------

def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME_LINUX}.service"


def _install_systemd(cmd: list[str]) -> Path:
    if not shutil.which("systemctl"):
        raise SystemExit("systemctl not found; install systemd or use a different supervisor.")
    unit = _render_systemd_unit(cmd)
    p = _systemd_unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(unit, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME_LINUX}.service"],
        check=True,
    )
    return p


def _uninstall_systemd() -> None:
    p = _systemd_unit_path()
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME_LINUX}.service"],
        capture_output=True,
    )
    if p.exists():
        p.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def _render_systemd_unit(cmd: list[str]) -> str:
    exec_start = " ".join(_shell_quote(a) for a in cmd)
    return f"""[Unit]
Description=eModul.pl relay/zone transition logger
After=network-online.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=60
# Keep the process well-behaved
Nice=10
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=default.target
"""


def _shell_quote(s: str) -> str:
    if not s or any(c in s for c in ' \t"\'$`\\'):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


# ---------- status helpers ----------

def _service_status() -> dict:
    plat = sys.platform
    if plat == "darwin":
        p = _launchd_plist_path()
        if not p.exists():
            return {"platform": "darwin", "installed": False}
        res = subprocess.run(
            ["launchctl", "list", SERVICE_NAME_MACOS],
            capture_output=True,
            text=True,
        )
        return {
            "platform": "darwin",
            "installed": True,
            "plist": str(p),
            "loaded": res.returncode == 0,
            "launchctl_output": res.stdout.strip() or res.stderr.strip(),
        }
    if plat.startswith("linux"):
        p = _systemd_unit_path()
        if not p.exists():
            return {"platform": "linux", "installed": False}
        res = subprocess.run(
            ["systemctl", "--user", "is-active", f"{SERVICE_NAME_LINUX}.service"],
            capture_output=True,
            text=True,
        )
        return {
            "platform": "linux",
            "installed": True,
            "unit": str(p),
            "active": res.stdout.strip(),
        }
    return {"platform": plat, "installed": False, "note": "unsupported"}
