"""Persistent CLI config stored at ~/.config/emodul/config.json (chmod 600)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    override = os.environ.get("EMODUL_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".config" / "emodul"


@dataclass(frozen=True)
class Config:
    token: str | None = None
    user_id: int | None = None
    email: str | None = None  # set by `auth login`; enables keychain-backed auto-refresh
    default_udid: str | None = None
    base_url: str = "https://emodul.pl"
    language: str = "pl"
    # Unlocked menu PINs: {udid: {menu_type: {id: pin}}}
    pins: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return _config_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if not p.exists():
            return cls()
        with p.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def save(self) -> Path:
        d = _config_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = self.path()
        with p.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        os.chmod(p, 0o600)
        return p

    def with_updates(self, **kwargs: Any) -> "Config":
        data = asdict(self)
        data.update(kwargs)
        return Config(**data)

    def require_auth(self) -> None:
        if not self.token or not self.user_id:
            raise SystemExit(
                "Not authenticated. Run `emodul auth login` or "
                "`emodul auth import-token <token> --user-id <id>`."
            )

    def resolve_udid(self, override: str | None) -> str:
        udid = override or self.default_udid
        if not udid:
            raise SystemExit(
                "No module selected. Pass --module <udid> or run "
                "`emodul modules select <udid|name>`."
            )
        return udid
