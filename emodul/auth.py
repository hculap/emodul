"""Keychain-backed auto-refresh: on 401, re-authenticate and retry once.

Uses the cross-platform `keyring` library: macOS Keychain, GNOME Keyring,
KWallet, or Windows Credential Locker — whichever the OS provides.
"""
from __future__ import annotations

from typing import Callable

import keyring
import keyring.errors

from emodul.api import ApiClient
from emodul.config import Config
from emodul.format import err_console

KEYRING_SERVICE = "emodul"


class RefreshUnavailable(RuntimeError):
    """Raised when auto-refresh can't proceed (no email, no password, etc.)."""


def set_password(email: str, password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, email, password)


def get_password(email: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, email)
    except keyring.errors.KeyringError:
        return None


def delete_password(email: str) -> bool:
    try:
        keyring.delete_password(KEYRING_SERVICE, email)
        return True
    except keyring.errors.PasswordDeleteError:
        return False
    except keyring.errors.KeyringError:
        return False


def make_refresher(
    config: Config,
    persist: Callable[[str, int], None],
) -> Callable[[ApiClient], None]:
    """Return a refresher closure suitable for ApiClient(refresher=...).

    `persist(token, user_id)` is called after a successful re-auth so the new
    token is saved to disk for the next process.
    """

    def refresh(client: ApiClient) -> None:
        if not config.email:
            raise RefreshUnavailable(
                "No email in config; run `emodul auth login` to enable auto-refresh."
            )
        password = get_password(config.email)
        if not password:
            raise RefreshUnavailable(
                f"No password in keyring for {config.email!r}; "
                "run `emodul auth login` to store it."
            )
        err_console.print(
            f"[yellow]token rejected; re-authenticating as {config.email}…[/yellow]"
        )
        body = client.authenticate(config.email, password)
        token = body.get("token")
        user_id = body.get("user_id")
        if not token or not user_id:
            raise RefreshUnavailable(f"unexpected auth response: {body}")
        client.token = token
        client.user_id = int(user_id)
        persist(token, int(user_id))
        err_console.print("[green]auto-refresh ok.[/green]")

    return refresh
