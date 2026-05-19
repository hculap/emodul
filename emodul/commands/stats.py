"""`emodul stats ...` — historical charts (linear / column / CSV export)."""
from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Iterator

import click

from emodul.format import dump_json, err_console

PERIODS = ["day", "week", "month", "year", "total"]

# YYYY-MM or YYYY-MM-DD; relative "Nm" (months ago) or "Ny" (years ago) or "now".
_RANGE_RE = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$")


def _parse_yyyymm(value: str, *, default_today: bool = False) -> tuple[int, int]:
    """Return (year, month). Accepts YYYY-MM, YYYY-MM-DD, Nm, Ny, 'now'."""
    v = value.strip().lower()
    today = dt.date.today()
    if v in ("now", "today"):
        return today.year, today.month
    if v.endswith("m") and v[:-1].isdigit():
        n = int(v[:-1])
        d = today.replace(day=1) - dt.timedelta(days=1)
        for _ in range(n - 1):
            d = d.replace(day=1) - dt.timedelta(days=1)
        return d.year, d.month
    if v.endswith("y") and v[:-1].isdigit():
        return today.year - int(v[:-1]), today.month
    m = _RANGE_RE.match(v)
    if not m:
        raise click.BadParameter(
            f"unrecognized date {value!r}; use YYYY-MM, YYYY-MM-DD, 'Nm', 'Ny', or 'now'"
        )
    return int(m.group(1)), int(m.group(2))


def _iter_months(since: tuple[int, int], until: tuple[int, int]) -> Iterator[tuple[int, int]]:
    y, mo = since
    end_y, end_mo = until
    if (y, mo) > (end_y, end_mo):
        raise click.BadParameter("--since must be ≤ --until")
    while (y, mo) <= (end_y, end_mo):
        yield y, mo
        mo += 1
        if mo == 13:
            mo, y = 1, y + 1


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def stats() -> None:
        """Historical statistics."""

    @stats.command("available")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def available(ctx, udid_arg: str | None) -> None:
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.stats_available(udid)
        dump_json(data)

    @stats.command("linear")
    @click.option("--period", type=click.Choice(PERIODS), default="day", show_default=True)
    @click.option("--month", type=int, help="1-12 (requires --year).")
    @click.option("--year", type=int)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def linear(
        ctx, period: str, month: int | None, year: int | None, udid_arg: str | None
    ) -> None:
        """Continuous chart (temperatures over time)."""
        if month and not year:
            raise click.BadParameter("--month requires --year")
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.stats_linear(udid, period=period, month=month, year=year)
        dump_json(data)

    @stats.command("column")
    @click.argument("state")
    @click.option("--period", type=click.Choice(PERIODS), default="day", show_default=True)
    @click.option("--month", type=int)
    @click.option("--year", type=int)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def column(
        ctx,
        state: str,
        period: str,
        month: int | None,
        year: int | None,
        udid_arg: str | None,
    ) -> None:
        """Bar-chart series. <state> = 'consumptions' or any series id from `stats available`."""
        if month and not year:
            raise click.BadParameter("--month requires --year")
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.stats_column(
                udid, state=state, period=period, month=month, year=year
            )
        dump_json(data)

    @stats.command("csv")
    @click.argument("state")
    @click.option("--period", type=click.Choice(PERIODS), default="day", show_default=True)
    @click.option("--language", default=None, help="Defaults to config.language.")
    @click.option("--month", type=int)
    @click.option("--year", type=int)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option("--out", type=click.Path(dir_okay=False), help="Write to file instead of stdout.")
    @click.pass_obj
    @wrap
    def csv_(
        ctx,
        state: str,
        period: str,
        language: str | None,
        month: int | None,
        year: int | None,
        udid_arg: str | None,
        out: str | None,
    ) -> None:
        """Download a series as CSV (server uses HTTP OPTIONS as the verb)."""
        if month and not year:
            raise click.BadParameter("--month requires --year")
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        lang = language or ctx.config.language
        with ctx.api() as api:
            text = api.stats_csv(
                udid, state=state, period=period, language=lang, month=month, year=year
            )
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            dump_json({"written": out, "bytes": len(text)})
        else:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")

    @stats.command("dump")
    @click.option(
        "--since",
        required=True,
        help="Start month. YYYY-MM, YYYY-MM-DD, 'Nm' (months ago), 'Ny' (years ago).",
    )
    @click.option(
        "--until",
        default="now",
        show_default=True,
        help="End month (same syntax as --since). Default: current month.",
    )
    @click.option(
        "--kind",
        type=click.Choice(["linear", "column", "csv"]),
        default="linear",
        show_default=True,
    )
    @click.option(
        "--state",
        default=None,
        help="Series name (required for kind=column or csv, e.g. 'consumptions').",
    )
    @click.option("--language", default=None, help="CSV language (defaults to config.language).")
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.option(
        "--out",
        type=click.Path(dir_okay=False),
        help="Write to file (CSV kind only; JSON kinds go to stdout).",
    )
    @click.option(
        "--skip-empty/--keep-empty",
        default=True,
        show_default=True,
        help="Drop months that returned no data (linear kind).",
    )
    @click.pass_obj
    @wrap
    def dump(
        ctx,
        since: str,
        until: str,
        kind: str,
        state: str | None,
        language: str | None,
        udid_arg: str | None,
        out: str | None,
        skip_empty: bool,
    ) -> None:
        """Fetch every month between --since and --until and merge into one payload.

        Examples:
          emodul stats dump --since 2025-03 --until 2026-05
          emodul stats dump --since 12m --kind csv --state consumptions --out year.csv
          emodul stats dump --since 6m --kind column --state consumptions
        """
        if kind in ("column", "csv") and not state:
            raise click.BadParameter(f"--state is required for --kind {kind}")
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        s_y, s_m = _parse_yyyymm(since)
        u_y, u_m = _parse_yyyymm(until)
        months = list(_iter_months((s_y, s_m), (u_y, u_m)))

        with ctx.api() as api:
            if kind == "linear":
                _dump_linear(api, udid, months, skip_empty)
            elif kind == "column":
                _dump_column(api, udid, state, months, skip_empty)
            else:
                _dump_csv(api, udid, state, months, language or ctx.config.language, out)


def _progress(y: int, m: int, total: int, i: int) -> None:
    err_console.print(f"[dim]  [{i}/{total}] {y}-{m:02d}…[/dim]")


def _dump_linear(api, udid: str, months: list[tuple[int, int]], skip_empty: bool) -> None:
    merged: dict[str, list[dict]] = {}
    months_kept: list[str] = []
    for i, (y, m) in enumerate(months, 1):
        _progress(y, m, len(months), i)
        data = api.stats_linear(udid, period="month", month=m, year=y)
        hist = (data.get("data") or {}).get("history") or {}
        has_any = any(hist.values())
        if not has_any and skip_empty:
            continue
        months_kept.append(f"{y}-{m:02d}")
        for series, points in hist.items():
            merged.setdefault(series, []).extend(points)
    dump_json(
        {
            "kind": "linear",
            "udid": udid,
            "months": months_kept,
            "series": {k: len(v) for k, v in merged.items()},
            "history": merged,
        }
    )


def _dump_column(
    api, udid: str, state: str, months: list[tuple[int, int]], skip_empty: bool
) -> None:
    merged: list[dict] = []
    months_kept: list[str] = []
    for i, (y, m) in enumerate(months, 1):
        _progress(y, m, len(months), i)
        data = api.stats_column(udid, state=state, period="month", month=m, year=y)
        rows = (data.get("data") or {}).get("history") or data.get("data") or []
        if not rows and skip_empty:
            continue
        months_kept.append(f"{y}-{m:02d}")
        if isinstance(rows, list):
            merged.extend(rows)
        else:
            merged.append({"month": f"{y}-{m:02d}", "data": rows})
    dump_json(
        {
            "kind": "column",
            "udid": udid,
            "state": state,
            "months": months_kept,
            "count": len(merged),
            "data": merged,
        }
    )


def _dump_csv(
    api,
    udid: str,
    state: str,
    months: list[tuple[int, int]],
    language: str,
    out_path: str | None,
) -> None:
    chunks: list[str] = []
    header: str | None = None
    for i, (y, m) in enumerate(months, 1):
        _progress(y, m, len(months), i)
        text = api.stats_csv(
            udid, state=state, period="month", language=language, month=m, year=y
        )
        if not text.strip():
            continue
        lines = text.splitlines()
        if not lines:
            continue
        if header is None:
            header = lines[0]
            chunks.append(header)
        chunks.extend(lines[1:])
    output = "\n".join(chunks) + ("\n" if chunks else "")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output)
        dump_json({"written": out_path, "rows": max(0, len(chunks) - 1)})
    else:
        sys.stdout.write(output)
