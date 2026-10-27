"""Reminders: checking them and the scheduled check (dam.cli.main)."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from dam.app import App
from dam.cli.main.common import EXIT_BATCH, EXIT_USER, app, print_error, session, store_of
from dam.profiles import Profile, ProfileStore
from dam.reminders import launchd, notify
from dam.reminders.engine import Due

# -- Phase 2: reminders, trays, collections, Ongoing ----------------------------------


def _parse_now(value: str | None) -> datetime | None:
    """``--now``: an ISO date-time; without an offset it is local time."""
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(
            "expected an ISO date-time such as 2026-11-03T09:00", param_hint="--now"
        ) from None
    return when.astimezone() if when.tzinfo is None else when


def _due_line(d: Due) -> str:
    parts = [notify.plain(d.title)]
    if d.date is not None:
        parts.append(d.date.isoformat())
    if d.amount is not None:
        parts.append(f"{d.amount:.2f}")
    return f"{d.occasion.isoformat()}  {notify.plain(d.tray_name or d.tray_id)}: {', '.join(parts)}"


SCHEDULE_HELP_WINDOWS = (
    "The daily reminder job is installed for you only on macOS. On Windows, schedule it\n"
    "yourself with Task Scheduler: create a daily task that runs the program\n"
    "  {cmd}\n"
    "with the arguments\n"
    '  --data-dir "{data}"{archive} remind\n'
    "every day at {hour:02d}:00. Nothing was changed."
)
SCHEDULE_HELP_LINUX = (
    "The daily reminder job is installed for you only on macOS. On Linux, schedule it\n"
    "yourself with a systemd user timer or cron, running\n"
    '  {cmd} --data-dir "{data}"{archive} remind\n'
    "every day at {hour:02d}:00 (cron: 0 {hour} * * * ...). Nothing was changed."
)


def _platform() -> str:
    return sys.platform


def _reminder_target(ctx: typer.Context) -> tuple[str, tuple[Path, str] | None]:
    """The LaunchAgent label of the chosen archive and, once there are several archives
    (or this is not "Main"), the (base folder, id) the job must name so that it keeps
    running this archive whichever one is in use later."""
    store: ProfileStore = store_of(ctx)
    profile: Profile = ctx.meta["dam.profile"]
    named = len(store.load()) > 1 or profile.id != launchd.MAIN_ID
    return launchd.label_for(profile.id), ((store.base, profile.id) if named else None)


def _schedule_help(ctx: typer.Context, a: App) -> str:
    cmd = launchd.dam_command()[0]
    text = SCHEDULE_HELP_WINDOWS if _platform() == "win32" else SCHEDULE_HELP_LINUX
    _label, archive = _reminder_target(ctx)
    return text.format(
        cmd=cmd,
        data=archive[0] if archive else a.app_paths.data_dir,
        archive=f" --archive {archive[1]}" if archive else "",
        hour=a.settings.reminders.hour,
    )


def _install_agent(ctx: typer.Context, a: App, yes: bool, force: bool) -> None:
    if _platform() != "darwin":
        print_error(_schedule_help(ctx, a))
        raise typer.Exit(EXIT_USER)
    label, archive = _reminder_target(ctx)
    path, hour = launchd.plist_path(label), a.settings.reminders.hour
    cmd = launchd.dam_command()
    typer.echo(f"LaunchAgent {path}:")
    typer.echo(launchd.plist(cmd, a.app_paths.data_dir, hour, label, archive))
    if not yes and not typer.confirm(f"Write {path} and load it?"):
        print_error("aborted")
        raise typer.Exit(EXIT_USER)
    try:
        launchd.install(cmd, a.app_paths.data_dir, hour, force=force, label=label, archive=archive)
    except launchd.LaunchdError as e:
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"installed: reminders are checked daily at {hour:02d}:00 and at login")


def _uninstall_agent(ctx: typer.Context, yes: bool) -> None:
    if _platform() != "darwin":
        typer.echo("no reminder job was installed by dam on this platform")
        return
    label, _archive = _reminder_target(ctx)
    path = launchd.plist_path(label)
    if not path.is_file():
        typer.echo(f"reminder LaunchAgent not installed ({path})")
        return
    typer.echo(f"LaunchAgent {path}:")
    typer.echo(path.read_text(errors="replace", encoding="utf-8"))
    if not yes and not typer.confirm(f"Unload and remove {path}?"):
        print_error("aborted")
        raise typer.Exit(EXIT_USER)
    try:
        launchd.uninstall(label=label)
    except launchd.LaunchdError as e:
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"removed {path}")


def _set_email_password(a: App) -> None:
    email = a.settings.reminders.email
    if email is None:
        print_error("error: set reminders.email (to, smtp_host, smtp_user) in settings.yaml first")
        raise typer.Exit(EXIT_USER)
    password = typer.prompt(
        f"Password for {email.smtp_user} at {email.smtp_host}",
        hide_input=True,
        confirmation_prompt=True,
    )
    try:
        notify.store_keychain_password(email.smtp_user, password)
    except Exception as e:  # noqa: BLE001 - never echo the details (they may quote input)
        print_error(f"error: could not store the password in the Keychain ({type(e).__name__})")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"password for {email.smtp_user} stored in the Keychain")


def _test_notification(a: App, dry_run: bool) -> None:
    channels = [n.id for n in notify.enabled_notifiers(a.settings)]
    if not channels:
        print_error("error: no reminder channel is enabled (reminders.mac / reminders.email)")
        raise typer.Exit(EXIT_USER)
    if dry_run:
        typer.echo(f"would send {notify.TEST_TITLE!r} via {', '.join(channels)}")
        typer.echo("dry run: nothing was sent")
        return
    results = notify.send_test(a.settings)
    for channel, error in results.items():
        if error is None:
            typer.echo(f"{channel}: sent {notify.TEST_TITLE!r}")
        else:
            print_error(f"error: {channel}: {error}")
    if any(error is not None for error in results.values()):
        raise typer.Exit(EXIT_BATCH)


@app.command()
def remind(
    ctx: typer.Context,
    now: Annotated[
        str | None,
        typer.Option(help="Check as of this time (ISO, e.g. 2026-11-03T09:00; local)."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only list what is due: send and mark nothing.")
    ] = False,
    install: Annotated[
        bool, typer.Option("--install", help="Install the daily LaunchAgent (asks first).")
    ] = False,
    uninstall: Annotated[
        bool, typer.Option("--uninstall", help="Remove the LaunchAgent (asks first).")
    ] = False,
    set_email_password: Annotated[
        bool,
        typer.Option("--set-email-password", help="Store the e-mail password in the Keychain."),
    ] = False,
    test_notification: Annotated[
        bool,
        typer.Option(
            "--test-notification",
            help="Send one test message through each enabled channel; marks nothing.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="With --install: replace a different plist.")
    ] = False,
) -> None:
    """Send the reminders that are due (macOS notification, optional e-mail), once.

    Works while the archive is unavailable (items are in the database).
    """
    chosen = [
        flag
        for flag, on in (
            ("--install", install),
            ("--uninstall", uninstall),
            ("--set-email-password", set_email_password),
            ("--test-notification", test_notification),
        )
        if on
    ]
    if len(chosen) > 1:
        raise typer.BadParameter(f"use only one of {', '.join(chosen)}")
    when = _parse_now(now)
    # no archive lock: the daily job must still send while the app is open, and it only
    # marks reminders as sent in the database, which SQLite handles across processes
    with session(ctx, warn_pending=False, require_archive=False) as a:
        if install:
            _install_agent(ctx, a, yes, force)
            return
        if uninstall:
            _uninstall_agent(ctx, yes)
            return
        if set_email_password:
            _set_email_password(a)
            return
        if test_notification:
            _test_notification(a, dry_run)
            return
        when = when or datetime.now().astimezone()
        if dry_run:
            dues = notify.due_now(a, when)
            for d in dues:
                typer.echo(_due_line(d))
            typer.echo("nothing due" if not dues else f"{len(dues)} due")
            typer.echo("dry run: nothing was sent or marked")
            return
        result = notify.run_reminders(a, now=when)
        if result.skipped:
            typer.echo(f"skipped: {result.skipped}")
            return
        for d in result.sent:
            typer.echo(_due_line(d))
        if result.sent:
            typer.echo(f"sent {len(result.sent)} reminder(s)")
        elif not result.errors:
            typer.echo("nothing due")
        for channel, message in result.errors.items():
            print_error(f"error: {channel}: {message}")
        if result.errors:
            raise typer.Exit(EXIT_BATCH)
