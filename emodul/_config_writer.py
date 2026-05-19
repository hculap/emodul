"""Safe writer for `claude_desktop_config.json` (and other user-managed JSON).

We touch a file the user also edits. Rules:
- Strict JSON parse (fail-loud on comments / trailing commas — refusing beats
  silently dropping unknown bits the user typed there on purpose).
- Atomic write via tempfile-on-same-FS + `os.replace`; `fsync` before rename.
- Timestamped backup, keep last 5; only made when target already exists.
- Shallow-merge at top level; replace at `mcpServers.<name>`; never touch
  sibling top-level keys (e.g. `preferences`).
- Concurrent writes serialized via `fcntl.flock` on a `.lock` next to target.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class ConfigWriteError(RuntimeError):
    """Caller-actionable error from the config writer (bad JSON, perms, etc.)."""


def load_config(path: Path) -> dict[str, Any]:
    """Parse JSON config, treating missing/empty as `{}`. Strict on syntax.

    Raises `ConfigWriteError` if the file exists but is unreadable, contains
    non-JSON content, or has a root that isn't an object — the user has to
    fix it manually rather than letting us silently rewrite their work.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigWriteError(f"Cannot read {path}: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigWriteError(
            f"{path} is not valid JSON ({exc.msg} at line {exc.lineno}, "
            f"col {exc.colno}). Fix it manually before running `emodul install`."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigWriteError(
            f"{path} root is {type(data).__name__}, expected object. "
            "Refusing to modify."
        )
    return data


def merge_mcp_server(
    config: dict[str, Any],
    name: str,
    entry: dict[str, Any],
    *,
    force: bool = False,
) -> tuple[dict[str, Any], str]:
    """Return `(new_config, action)` where action is one of:
    `"added"`, `"unchanged"`, `"updated"`, `"conflict"`.

    - "added": there was no `mcpServers.<name>` before.
    - "unchanged": entry already matches what we'd write — no-op.
    - "updated": entry existed with different content AND `force=True`.
    - "conflict": entry existed with different content AND `force=False` —
      caller should report the diff and bail.

    The merge preserves all other top-level keys and all sibling `mcpServers.*`
    entries unchanged.
    """
    new = {**config}
    servers = dict(new.get("mcpServers") or {})
    existing = servers.get(name)
    if existing is None:
        servers[name] = entry
        new["mcpServers"] = servers
        return new, "added"
    if existing == entry:
        return new, "unchanged"
    if not force:
        return new, "conflict"
    servers[name] = entry
    new["mcpServers"] = servers
    return new, "updated"


def remove_mcp_server(
    config: dict[str, Any], name: str
) -> tuple[dict[str, Any], bool]:
    """Return `(new_config, removed)`. Drops empty `mcpServers` block."""
    new = {**config}
    servers = dict(new.get("mcpServers") or {})
    if name not in servers:
        return new, False
    del servers[name]
    if servers:
        new["mcpServers"] = servers
    else:
        new.pop("mcpServers", None)
    return new, True


def _serialize(data: dict[str, Any]) -> bytes:
    """Canonical on-disk shape: 2-space indent, sorted top-level keys are NOT
    enforced (preserves user's order), trailing newline.
    """
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _make_backup(path: Path) -> Path | None:
    """Write `<path>.bak-YYYYMMDDTHHMMSS`. Returns the backup path or None
    if the source doesn't exist yet. Prunes older backups (keep last 5).
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    backup.write_bytes(path.read_bytes())
    _prune_backups(path, keep=5)
    return backup


def _prune_backups(path: Path, *, keep: int) -> None:
    """Delete backups older than the most recent `keep`."""
    pattern = f"{path.name}.bak-*"
    backups = sorted(path.parent.glob(pattern), reverse=True)
    for stale in backups[keep:]:
        with contextlib.suppress(OSError):
            stale.unlink()


def atomic_write(path: Path, data: dict[str, Any]) -> Path | None:
    """Write `data` as JSON to `path` atomically; return backup path (or None
    if no prior file existed). Creates parent dirs as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _make_backup(path)
    payload = _serialize(data)
    # NamedTemporaryFile in same dir → rename is atomic on the same filesystem.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return backup


@contextlib.contextmanager
def _lockfile(path: Path):
    """Serialize concurrent `emodul install` invocations via fcntl.flock on a
    sibling `.lock` file. On platforms without fcntl (Windows), no-op — the
    write is still safe but two parallel runs may both succeed with a
    last-writer-wins outcome (rare for a CLI install command).
    """
    try:
        import fcntl
    except ImportError:  # Windows
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_with_backup(path: Path, data: dict[str, Any]) -> Path | None:
    """Public entry: lock, then atomic_write. Returns backup path or None."""
    with _lockfile(path):
        return atomic_write(path, data)
