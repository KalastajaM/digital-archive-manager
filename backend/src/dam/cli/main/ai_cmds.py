"""The AI commands (dam.cli.main)."""

from datetime import datetime
from typing import Annotated

import typer

from dam.app import App
from dam.cli.main.common import EXIT_USER, app, print_error, session, table
from dam.errors import InvalidRequest

# -- Phase 3: AI ------------------------------------------------------------------------


def _ai_status(a: App) -> None:
    s = a.ai.status(refresh=True)  # the Keychain now, never a memo
    typer.echo(f"AI: {'on' if s['enabled'] else 'off'}")
    typer.echo(f"key: {'present' if s['has_key'] else 'missing'} (dam ai --set-key)")
    typer.echo(f"spend this month: €{s['month_spend_eur']:.2f} of €{s['budget_eur']:.2f}")
    typer.echo(f"models: small {s['models']['small']}, large {s['models']['large']}")
    typer.echo(f"excluded folders: {', '.join(s['exclude_folders']) or '(none)'}")
    if s["state_error"]:
        typer.echo(f"warning: {s['state_error']} (dam ai --on)")
    elif not s["switched_on"]:
        typer.echo("switched off with dam ai --off; dam ai --on turns it back on")
    elif not a.settings.ai.enabled:
        typer.echo("ai.enabled is false in settings.yaml")


def _ai_set_key() -> None:
    from dam.ai import keys

    key = typer.prompt("Anthropic API key", hide_input=True, confirmation_prompt=True)
    try:
        keys.set_key(key)
    except InvalidRequest as e:
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    except Exception as e:  # noqa: BLE001 - never echo the details (they may quote input)
        print_error(f"error: could not store the key in the Keychain ({type(e).__name__})")
        raise typer.Exit(EXIT_USER) from None
    typer.echo("API key stored in the Keychain (service dam-anthropic)")


def _ai_log(a: App, limit: int) -> None:
    rows = a.ai.recent(limit)
    if not rows:
        typer.echo("no AI calls")
        return
    table(
        ["when", "task", "model", "files", "in", "out", "cost €", "outcome", "ms"],
        [
            [
                datetime.fromtimestamp(r["at"]).strftime("%Y-%m-%d %H:%M"),
                r["task"],
                r["model"],
                str(len(r["files"])),
                str(r["input_tokens"]),
                str(r["output_tokens"]),
                f"{r['cost_eur']:.4f}",
                r["outcome"] + (f" ({r['error']})" if r["error"] else ""),
                str(r["duration_ms"]),
            ]
            for r in rows
        ],
    )


@app.command("ai")
def ai_cmd(
    ctx: typer.Context,
    set_key: Annotated[
        bool, typer.Option("--set-key", help="Store the Anthropic API key in the Keychain.")
    ] = False,
    clear_key: Annotated[
        bool, typer.Option("--clear-key", help="Remove the API key from the Keychain.")
    ] = False,
    status: Annotated[
        bool, typer.Option("--status", help="On/off, key present, spend and cap (default).")
    ] = False,
    log: Annotated[bool, typer.Option("--log", help="Print the call log, newest first.")] = False,
    on: Annotated[bool, typer.Option("--on", help="Switch AI on.")] = False,
    off: Annotated[bool, typer.Option("--off", help="Switch AI off (the key stays).")] = False,
    limit: Annotated[int, typer.Option(help="With --log: at most this many rows.")] = 50,
) -> None:
    """The optional AI help: its key, switch, spend and call log. The key is only ever
    in the macOS Keychain; it is never printed."""
    chosen = [
        flag
        for flag, chosen in (
            ("--set-key", set_key),
            ("--clear-key", clear_key),
            ("--status", status),
            ("--log", log),
            ("--on", on),
            ("--off", off),
        )
        if chosen
    ]
    if len(chosen) > 1:
        raise typer.BadParameter(f"use only one of {', '.join(chosen)}")
    if limit < 1:
        raise typer.BadParameter("--limit must be at least 1")
    if set_key:
        _ai_set_key()
        return
    if clear_key:
        from dam.ai import keys

        try:
            keys.clear_key()
        except Exception as e:  # noqa: BLE001 - never echo the details
            print_error(f"error: could not reach the Keychain ({type(e).__name__})")
            raise typer.Exit(EXIT_USER) from None
        typer.echo("API key removed from the Keychain")
        return
    with session(ctx, warn_pending=False, require_archive=False, write=on or off) as a:
        if log:
            _ai_log(a, limit)
            return
        if on or off:
            a.ai.set_enabled(on)
        _ai_status(a)
