"""Authentication: login, import-token, whoami, logout, forget-password."""
from __future__ import annotations

import click

from emodul import auth as auth_kc
from emodul.format import console, dump_json


def register(cli: click.Group, wrap) -> None:
    @cli.group()
    def auth() -> None:
        """Manage API credentials."""

    @auth.command("login")
    @click.option("--email", default=None,
                  help="(terminal flow only — ignored with --browser)")
    @click.option("--password", default=None,
                  help="(terminal flow only — ignored with --browser)")
    @click.option("--language-id", default=18, show_default=True, help="18 = Polish.")
    @click.option(
        "--browser/--terminal",
        "use_browser",
        default=None,
        help="Browser flow opens a local form (password never seen by the agent). "
        "Terminal flow prompts in stdin. Default: browser when stdin is not a TTY "
        "(AI-agent context), terminal when interactive.",
    )
    @click.option(
        "--port",
        type=int,
        default=None,
        help="[--browser] Local bind port. Default: random free port.",
    )
    @click.option(
        "--no-open",
        is_flag=True,
        help="[--browser] Don't auto-open the browser; print URL only.",
    )
    @click.option(
        "--timeout",
        type=int,
        default=300,
        show_default=True,
        help="[--browser] Seconds to wait for the user to submit the form.",
    )
    @click.option(
        "--no-keychain",
        is_flag=True,
        help="Don't store password in OS keychain (disables auto-refresh).",
    )
    @click.pass_obj
    @wrap
    def login(
        ctx,
        email: str | None,
        password: str | None,
        language_id: int,
        use_browser: bool | None,
        port: int | None,
        no_open: bool,
        timeout: int,
        no_keychain: bool,
    ) -> None:
        """Exchange username + password for a JWT and (by default) store the
        password in the OS keychain so the CLI can auto-refresh on 401.

        Two flows:
        - Browser (recommended for AI-agent contexts): opens a local
          127.0.0.1 form. Agent never sees the password.
        - Terminal: classic stdin prompt.
        """
        import sys

        if use_browser is None:
            use_browser = not sys.stdin.isatty()

        if use_browser:
            from emodul.web_auth import web_login_flow
            result = web_login_flow(
                base_url=ctx.config.base_url,
                language_id=language_id,
                open_browser=not no_open,
                port=port,
                timeout=timeout,
            )
            token = result["token"]
            user_id = result["user_id"]
            email = result["email"]
            password = result["password"]
        else:
            if not email:
                email = click.prompt("Email")
            if not password:
                password = click.prompt("Password", hide_input=True)
            with ctx.api() as api:
                body = api.authenticate(email, password, language_id)
            token = body.get("token")
            user_id = body.get("user_id")
            if not token or not user_id:
                raise SystemExit(f"Unexpected auth response: {body}")

        new_cfg = ctx.config.with_updates(
            token=token, user_id=int(user_id), email=email
        )
        new_cfg.save()
        ctx.config = new_cfg
        keychain_ok = False
        if not no_keychain and password:
            try:
                auth_kc.set_password(email, password)
                keychain_ok = True
            except Exception as exc:
                console.print(
                    f"[yellow]Keychain unavailable ({exc}); "
                    "auto-refresh disabled. Use --no-keychain to silence.[/yellow]"
                )
        if ctx.json:
            dump_json(
                {
                    "user_id": user_id,
                    "email": email,
                    "token_saved": True,
                    "auto_refresh": keychain_ok,
                    "flow": "browser" if use_browser else "terminal",
                }
            )
        else:
            extra = "[dim](auto-refresh on)[/dim]" if keychain_ok else ""
            console.print(
                f"[green]Logged in as {email} (user_id={user_id}).[/green] {extra}"
            )

    @auth.command("import-token")
    @click.argument("token")
    @click.option("--user-id", type=int, required=True)
    @click.option(
        "--email",
        default=None,
        help="Email to associate. Run `auth login` later to also store password "
        "in keychain and enable auto-refresh.",
    )
    @click.pass_obj
    def import_token(ctx, token: str, user_id: int, email: str | None) -> None:
        """Save an existing JWT (e.g. grabbed from browser DevTools)."""
        new_cfg = ctx.config.with_updates(token=token, user_id=user_id, email=email)
        path = new_cfg.save()
        ctx.config = new_cfg
        if ctx.json:
            dump_json({"saved_to": str(path), "user_id": user_id, "email": email})
        else:
            console.print(f"[green]Token saved → {path}[/green]")

    @auth.command("whoami")
    @click.pass_obj
    @wrap
    def whoami(ctx) -> None:
        """Show current account, default module, and auto-refresh status."""
        cfg = ctx.config
        has_keychain_password = bool(
            cfg.email and auth_kc.get_password(cfg.email)
        )
        info = {
            "user_id": cfg.user_id,
            "email": cfg.email,
            "default_udid": cfg.default_udid,
            "base_url": cfg.base_url,
            "language": cfg.language,
            "token_present": bool(cfg.token),
            "auto_refresh": has_keychain_password,
        }
        if cfg.token and cfg.user_id:
            with ctx.api() as api:
                try:
                    info["server_info"] = api.user_info()
                except Exception as exc:
                    info["server_info_error"] = str(exc)
        dump_json(info)

    @auth.command("forget-password")
    @click.pass_obj
    def forget_password(ctx) -> None:
        """Remove the stored password from the OS keychain (disables auto-refresh)."""
        if not ctx.config.email:
            raise SystemExit("No email in config; nothing to forget.")
        ok = auth_kc.delete_password(ctx.config.email)
        dump_json({"email": ctx.config.email, "removed": ok})

    @auth.command("logout")
    @click.pass_obj
    def logout(ctx) -> None:
        """Clear stored token + user_id (keep default udid)."""
        new_cfg = ctx.config.with_updates(token=None, user_id=None)
        new_cfg.save()
        console.print("[yellow]Local credentials cleared.[/yellow]")
