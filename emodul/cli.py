"""Root click group + subcommand registration."""
from __future__ import annotations

import sys
from typing import Any

import click

from emodul import __version__
from emodul.api import ApiClient, EmodulApiError
from emodul.auth import make_refresher
from emodul.commands import alarms, auth, menu, misc, modules, schedules, settings, stats, watch, zones
from emodul.config import Config
from emodul.format import dump_json, err_console


class Ctx:
    def __init__(self, config: Config, json_out: bool) -> None:
        self.config = config
        self.json = json_out
        self._module_cache: list[dict] | None = None

    def _persist_new_token(self, token: str, user_id: int) -> None:
        new_cfg = self.config.with_updates(token=token, user_id=user_id)
        new_cfg.save()
        self.config = new_cfg

    def resolve_module_udid(self, query_or_none: str | None) -> str:
        """Resolve -m argument: full udid, partial udid prefix, or name substring.

        Defaults to config.default_udid when nothing passed.
        """
        q = query_or_none or self.config.default_udid
        if not q:
            raise SystemExit(
                "No module selected. Pass -m <udid|name> or run "
                "`emodul modules select <udid|name>`."
            )
        # Fast path: looks like a full hex udid (32 chars) — assume it's the udid.
        if len(q) == 32 and all(c in "0123456789abcdef" for c in q.lower()):
            return q
        # Otherwise, look it up against the module list (cached per Ctx).
        if self._module_cache is None:
            with self.api() as api:
                self._module_cache = api.list_modules()
        ql = q.lower()
        for m in self._module_cache:
            if (m.get("udid") or "").lower() == ql:
                return m["udid"]
        for m in self._module_cache:
            if (m.get("udid") or "").lower().startswith(ql):
                return m["udid"]
        matches = [m for m in self._module_cache if ql in (m.get("name") or "").lower()]
        if len(matches) == 1:
            return matches[0]["udid"]
        if not matches:
            raise SystemExit(f"No module matches {q!r}.")
        raise SystemExit(
            f"Ambiguous module {q!r}: matched "
            f"{', '.join(m.get('name','?') for m in matches)}"
        )

    def api(self) -> ApiClient:
        refresher = (
            make_refresher(self.config, self._persist_new_token)
            if self.config.email
            else None
        )
        return ApiClient(
            base_url=self.config.base_url,
            token=self.config.token,
            user_id=self.config.user_id,
            refresher=refresher,
        )

    def emit(self, payload: Any, render_pretty: Any = None) -> None:
        if self.json or render_pretty is None:
            dump_json(payload)
        else:
            render_pretty(payload)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--json", "json_out", is_flag=True, help="Emit machine-readable JSON.")
@click.version_option(__version__, prog_name="emodul")
@click.pass_context
def cli(ctx: click.Context, json_out: bool) -> None:
    """Unofficial CLI for Tech Sterowniki eModul.pl.

    Designed to be driven both interactively and from an AI agent.
    Pass --json on any command for stable structured output.
    """
    cfg = Config.load()
    ctx.obj = Ctx(cfg, json_out)


@cli.result_callback()
@click.pass_context
def _handle_errors(ctx: click.Context, result: Any, **_: Any) -> None:
    # Click does its own error handling; this is a no-op hook.
    return result


def _wrap_api_errors(fn):
    """Decorator: pretty-print EmodulApiError instead of raw traceback."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except EmodulApiError as exc:
            err_console.print(f"[red]API {exc.status}[/red] on {exc.path}: {exc.body}")
            if exc.status in (401, 403):
                err_console.print(
                    "Token rejected. Re-grab it from browser DevTools "
                    "and run `emodul auth import-token`."
                )
            sys.exit(2)

    return wrapper


auth.register(cli, _wrap_api_errors)
modules.register(cli, _wrap_api_errors)
zones.register(cli, _wrap_api_errors)
menu.register(cli, _wrap_api_errors)
stats.register(cli, _wrap_api_errors)
alarms.register(cli, _wrap_api_errors)
misc.register(cli, _wrap_api_errors)
watch.register(cli, _wrap_api_errors)
settings.register(cli, _wrap_api_errors)
schedules.register(cli, _wrap_api_errors)


if __name__ == "__main__":
    cli()
