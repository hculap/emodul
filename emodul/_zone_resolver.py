"""Resolve a zone query (name substring or numeric id) to a flattened row.

Shared between CLI (`commands/zones._resolve_zone`) and MCP tools to keep
the semantics aligned. Earlier the CLI fell through from numeric-id to
substring on miss; this version short-circuits — pass digits → id-only,
pass non-digits → name-only. Removes accidental matches like `"3"`
substring-matching `"Pokój 3"`.
"""
from __future__ import annotations


def resolve_zone(rows: list[dict], query: str) -> dict | None:
    """Return the single matching zone row, or None if not found / ambiguous.

    Callers should treat `None` as "not found OR ambiguous" and message
    accordingly (with the list of candidates if they want better UX).
    """
    if query.isdigit():
        zid = int(query)
        for row in rows:
            if row.get("zone_id") == zid:
                return row
        return None
    q = query.lower()
    matches = [r for r in rows if q in (r.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]
    return None
