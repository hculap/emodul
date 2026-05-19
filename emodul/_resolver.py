"""Resolve a `-m <module>` argument to a controller UDID.

Shared between CLI (`Ctx.resolve_module_udid`) and MCP server.
"""
from __future__ import annotations

from typing import Iterable


def resolve_module_udid(query: str | None, modules: Iterable[dict], default_udid: str | None = None) -> str:
    """Accept full hex udid, prefix, or name substring; fall back to `default_udid`.

    Raises:
        LookupError: if no match or ambiguous.
        ValueError: if neither `query` nor `default_udid` given.
    """
    q = query or default_udid
    if not q:
        raise ValueError("No module specified and no default set.")

    # Fast path: full 32-char hex udid
    if len(q) == 32 and all(c in "0123456789abcdef" for c in q.lower()):
        return q

    mods = list(modules)
    ql = q.lower()

    # Exact udid
    for m in mods:
        if (m.get("udid") or "").lower() == ql:
            return m["udid"]

    # Udid prefix
    for m in mods:
        if (m.get("udid") or "").lower().startswith(ql):
            return m["udid"]

    # Name substring
    matches = [m for m in mods if ql in (m.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]["udid"]
    if not matches:
        raise LookupError(f"No module matches {q!r}.")
    names = ", ".join(m.get("name", "?") for m in matches)
    raise LookupError(f"Ambiguous module {q!r}: matched {names}")
