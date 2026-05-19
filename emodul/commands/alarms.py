"""`emodul alarms ...` — historical alarms / warnings / notifications."""
from __future__ import annotations

import datetime as dt

import click

from emodul.format import dump_json

ALARM_TYPES = ["all", "alarm", "warning", "notification"]


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def alarms() -> None:
        """Alarm history."""

    @alarms.command("history")
    @click.option(
        "--from",
        "from_date",
        default=None,
        help="YYYY-MM-DD (default: 30 days ago).",
    )
    @click.option("--to", "to_date", default=None, help="YYYY-MM-DD (default: today).")
    @click.option(
        "--type",
        "alarm_type",
        type=click.Choice(ALARM_TYPES),
        default="all",
        show_default=True,
    )
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def history(
        ctx,
        from_date: str | None,
        to_date: str | None,
        alarm_type: str,
        udid_arg: str | None,
    ) -> None:
        today = dt.date.today()
        to_d = to_date or today.isoformat()
        from_d = from_date or (today - dt.timedelta(days=30)).isoformat()
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.alarm_history(
                udid, from_date=from_d, to_date=to_d, alarm_type=alarm_type
            )
        dump_json(data)

    @alarms.command("ack")
    @click.argument("alarm_id", type=int)
    @click.option("-m", "--module", "udid_arg", default=None)
    @click.pass_obj
    @wrap
    def ack(ctx, alarm_id: int, udid_arg: str | None) -> None:
        """Acknowledge / dismiss an alarm popup by id."""
        ctx.config.require_auth()
        udid = ctx.resolve_module_udid(udid_arg)
        with ctx.api() as api:
            data = api.acknowledge_alarm(udid, alarm_id)
        dump_json(data)
