"""Shared helpers for MCP tool implementations.

All tools follow the same shape: load config, build ApiClient (with auth
auto-refresh wired), run a SYNC body via anyio.to_thread.run_sync, return a
JSON-safe dict. These helpers reduce boilerplate.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from emodul.api import ApiClient, EmodulApiError
from emodul.auth import make_refresher
from emodul.config import Config


class AuthRequired(RuntimeError):
    """Raised when a tool needs an authenticated session and there isn't one."""


def _persist_token(token: str, user_id: int) -> None:
    """Persist a refreshed token back to disk (used by the auth refresher)."""
    cfg = Config.load()
    new_cfg = cfg.with_updates(token=token, user_id=user_id)
    new_cfg.save()


@contextmanager
def open_api(require_auth: bool = True):
    """Open an ApiClient with auto-refresh wired. Yields (api, config)."""
    cfg = Config.load()
    if require_auth and not (cfg.token and cfg.user_id):
        raise AuthRequired(
            "Not authenticated. Call the `login_browser` tool first, "
            "or run `emodul auth login --browser` in a terminal on the host."
        )
    refresher = (
        make_refresher(cfg, _persist_token) if cfg.email else None
    )
    api = ApiClient(
        base_url=cfg.base_url,
        token=cfg.token,
        user_id=cfg.user_id,
        refresher=refresher,
    )
    try:
        yield api, cfg
    finally:
        api.close()


def resolve_udid(query: str | None, api: ApiClient, cfg: Config) -> str:
    """Resolve -m argument via shared helper. Raises ValueError on failure."""
    from emodul._resolver import resolve_module_udid as _resolve

    q = query or cfg.default_udid
    if not q:
        raise ValueError(
            "No module specified and no default set. "
            "Call `list_modules` then `set_default_module`, or pass `module` explicitly."
        )
    if len(q) == 32 and all(c in "0123456789abcdef" for c in q.lower()):
        return q
    return _resolve(q, api.list_modules(), cfg.default_udid)


def err_response(message: str, **extra: Any) -> dict:
    """Standard error envelope returned from a tool (NOT an exception)."""
    return {"ok": False, "error": message, **extra}


def ok_response(**data: Any) -> dict:
    """Standard success envelope returned from a tool."""
    return {"ok": True, **data}


def safely(fn):
    """Decorator: convert known exceptions into error envelopes.

    Tools should NEVER raise to the top level — that kills the MCP server.
    Fail loudly at decoration time if applied to a sync function (otherwise
    `await fn(...)` would silently TypeError into an opaque "Internal error"
    envelope).
    """
    import asyncio
    import functools
    import logging

    if not asyncio.iscoroutinefunction(fn):
        raise TypeError(
            f"@safely requires `async def`; got plain function {fn.__name__!r}. "
            "MCP tools must be async (they use anyio.to_thread internally)."
        )

    log = logging.getLogger(f"emodul.mcp.tool.{fn.__name__}")

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except AuthRequired as exc:
            return err_response(str(exc), code="auth_required")
        except EmodulApiError as exc:
            # Log at warning — recoverable / expected operational failure.
            log.warning(
                "api_error status=%s path=%s body=%r",
                exc.status, exc.path, exc.body,
            )
            return err_response(
                f"eModul API {exc.status} on {exc.path}: {exc.body}",
                code="api_error",
                status=exc.status,
            )
        except LookupError as exc:
            return err_response(str(exc), code="not_found")
        except ValueError as exc:
            return err_response(str(exc), code="bad_input")
        except Exception as exc:  # noqa: BLE001
            # Full traceback to stderr (operator-visible via MCP server logs).
            # User-facing message stays terse — never echo repr(exc) since
            # httpx-like errors may include the request URL with user_id.
            log.exception("tool crashed: %s", type(exc).__name__)
            return err_response(
                f"Internal error in tool (see server logs): {type(exc).__name__}",
                code="internal",
            )

    return wrapper
