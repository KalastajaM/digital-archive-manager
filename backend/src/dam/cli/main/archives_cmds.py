"""Several archives (profiles): the archives commands (dam.cli.main)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from dam import setup as dam_setup
from dam.cli.main.common import EXIT_USER, archives_app, print_error, store_of, table
from dam.cli.main.setup_cmds import init
from dam.errors import InvalidRequest, NotFound
from dam.profiles import ServeLock
from dam.reminders import launchd
from dam.services.archives import ArchiveService

# -- several archives (profiles) -----------------------------------------------------


@contextmanager
def _archive_errors() -> Iterator[None]:
    try:
        yield
    except (NotFound, InvalidRequest) as e:
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None


def _pin_notice() -> None:
    """A reminder job installed before archives existed follows the archive in use."""
    if launchd.pins_archive() is False:
        typer.echo(
            "\nNote: the reminder job installed earlier does not name an archive, so it checks "
            "the one in use.\nPin it to Main with: dam --archive Main remind --install --force"
        )


@archives_app.command("list")
def archives_list(ctx: typer.Context) -> None:
    """List the archives; the one in use is marked with *."""
    with _archive_errors():
        store = store_of(ctx)
        profiles = store.load(persist=True)
        problems = store.root_problems()
        rows = []
        for p in profiles:
            elsewhere = ServeLock.holder(p.data_dir)
            where = ""
            if elsewhere and elsewhere.get("command"):
                where = f"in use by a dam command ({elsewhere['command']})"
            elif elsewhere:
                port = elsewhere.get("port")
                where = f"open in another window{f' (port {port})' if port else ''}"
            rows.append(
                [
                    "*" if p.active else "",
                    p.name,
                    p.id,
                    p.archive_root or "(not set up yet)",
                    where or problems.get(p.id, ""),
                ]
            )
        table(["", "NAME", "ID", "ARCHIVE FOLDER", "NOTE"], rows)


@archives_app.command("add")
def archives_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the new archive.")],
    color: Annotated[
        str | None,
        typer.Option("--color", help="Colour like #3b6fd4 (default: the next free one)."),
    ] = None,
    folder: Annotated[
        Path | None,
        typer.Option("--folder", help="Its archive folder (skips the questions)."),
    ] = None,
    demo: Annotated[
        bool,
        typer.Option("--demo", help="Build the fictional demo archive in --folder (new or empty)."),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask before writing the setting.")
    ] = False,
    layout: Annotated[
        str | None,
        typer.Option("--layout", help="Start it with this starter layout (see `dam init`)."),
    ] = None,
    numbered: Annotated[
        bool, typer.Option("--numbered/--no-numbered", help="Number the layout's folders.")
    ] = True,
) -> None:
    """Add an archive and set it up (the same questions as `dam init`).

    Its data folder is made inside the app's data folder. The archive in use does not
    change: `dam archives switch NAME` (or --archive NAME) opens the new one.
    """
    store = store_of(ctx)
    if demo and folder is None:
        print_error("error: --demo needs --folder (a new or empty folder for the demo archive)")
        raise typer.Exit(EXIT_USER)
    with _archive_errors():
        profiles = store.load(persist=True)
        current = next(p for p in profiles if p.active)
        store.check_new_name(name)
        if folder is not None and not demo:
            # a folder that clashes with another archive is refused before anything is added
            check = dam_setup.check_archive_path(
                str(folder), current.paths, guard=store.root_guard(None)
            )
            if not check.ok and not check.can_create:
                raise InvalidRequest(check.message)
        if demo:
            service = ArchiveService(store, current.id, None, current.paths)
            made = service.add(name, color, str(folder))
            profile = store.find(made["id"])
            typer.echo(f"Added '{profile.name}' with a demo archive in {profile.archive_root}")
            typer.echo(f"Open it with: dam --archive {profile.id} serve")
            _pin_notice()
            return
        profile = store.add(name, color)
    typer.echo(f"Added '{profile.name}' (data folder {profile.data_dir}).")
    ctx.obj = profile.data_dir
    ctx.meta["dam.profile"] = profile
    try:
        init(ctx, archive=folder, yes=yes, layout=layout, numbered=numbered)
    except (typer.Exit, typer.Abort):
        typer.echo(
            f"'{profile.name}' is added but not set up yet: run `dam --archive {profile.id} init`."
        )
        raise
    typer.echo(f"Open it with: dam --archive {profile.id} serve")
    _pin_notice()


@archives_app.command("switch")
def archives_switch(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="Name or id.")]
) -> None:
    """Make an archive the one `dam` uses by default (windows already open keep theirs)."""
    with _archive_errors():
        profile = store_of(ctx).set_active(name)
    typer.echo(f"'{profile.name}' is now the archive in use.")
    if profile.archive_root is None:
        typer.echo(f"It is not set up yet: run `dam --archive {profile.id} init`.")
    _pin_notice()


@archives_app.command("rename")
def archives_rename(
    ctx: typer.Context,
    old: Annotated[str, typer.Argument(help="Name or id.")],
    new: Annotated[str, typer.Argument(help="The new name.")],
) -> None:
    """Rename an archive (its id and its folders stay as they are)."""
    with _archive_errors():
        profile = store_of(ctx).set_name(old, new)
    typer.echo(f"Renamed to '{profile.name}' (id {profile.id}).")


@archives_app.command("color")
def archives_color(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name or id.")],
    color: Annotated[str, typer.Argument(help="Colour like #3b6fd4.")],
) -> None:
    """Change the colour an archive is shown with."""
    with _archive_errors():
        profile = store_of(ctx).recolor(name, color)
    typer.echo(f"'{profile.name}' is now {profile.color}.")


@archives_app.command("forget")
def archives_forget(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name or id.")],
    switch_to: Annotated[
        str | None,
        typer.Option("--switch-to", help="Needed for the archive in use: the one to use instead."),
    ] = None,
) -> None:
    """Remove an archive from the list. Nothing is deleted.

    Neither its data folder nor its archive folder is touched; the paths are printed so
    you can remove them yourself if you want to. The last archive cannot be forgotten.
    """
    with _archive_errors():
        gone = store_of(ctx).forget(name, switch_to)
    typer.echo(f"Forgot '{gone.name}'. Nothing was deleted:")
    typer.echo(f"  data folder:    {gone.data_dir}")
    typer.echo(f"  archive folder: {gone.archive_root or '(none)'}")
    typer.echo("Remove them by hand if you no longer want them.")


@archives_app.command("where")
def archives_where(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="Name or id.")]
) -> None:
    """Print where an archive's data folder and archive folder are."""
    with _archive_errors():
        profile = store_of(ctx).find(name)
    typer.echo(f"data folder:    {profile.data_dir}")
    typer.echo(f"archive folder: {profile.archive_root or '(not set up yet)'}")
