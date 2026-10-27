"""Stars and Important, and the ##. Ongoing commands (dam.cli.main)."""

from pathlib import PurePosixPath
from typing import Annotated

import typer

from dam.cli.main.common import (
    EXIT_BATCH,
    EXIT_USER,
    app,
    finish,
    ongoing_app,
    print_error,
    session,
    show_ops,
    table,
)

# -- stars: ★ Ongoing and ! Important ---------------------------------------------------


def _member_rows(c, group_names: dict[int, str] | None = None) -> list[list[str]]:
    """A built-in collection's members, A-Z by path (missing ones by drive id)."""
    rows = []
    for m in c.members:
        shown = m.path if m.path and not m.missing else f"(missing) {m.drive_id}"
        row = [shown]
        if group_names is not None:
            row.insert(0, group_names.get(m.group_id, "-") if m.group_id else "-")
        rows.append(row)
    return sorted(rows, key=lambda r: [x.casefold() for x in r])


def _group_names(c) -> dict[int, str]:
    """Each group's path from the top, "Houses › Hillside"."""
    by_id = {g.id: g for g in c.groups}

    def path(gid: int) -> str:
        names, seen = [], set()
        cur: int | None = gid
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            names.append(by_id[cur].name)
            cur = by_id[cur].parent_id
        return " › ".join(reversed(names))

    return {gid: path(gid) for gid in by_id}


TARGETS = Annotated[list[str], typer.Argument(metavar="PATH-OR-DRIVE-ID...")]


@app.command()
def star(ctx: typer.Context, targets: TARGETS) -> None:
    """Star files or folders (★ Ongoing). Never moves or renames them."""
    with session(ctx, write=True) as a:
        ids = [a.browse.resolve(t).drive_id for t in targets]
        a.marks.star(ids)
        typer.echo(f"starred {len(ids)} item(s)")


@app.command()
def unstar(ctx: typer.Context, targets: TARGETS) -> None:
    """Take the ★ off files or folders."""
    with session(ctx, write=True) as a:
        ids = [a.browse.resolve(t).drive_id for t in targets]
        a.marks.unstar(ids)
        typer.echo(f"unstarred {len(ids)} item(s)")


@app.command()
def starred(ctx: typer.Context) -> None:
    """The ★ starred files and folders."""
    with session(ctx, require_archive=False) as a:
        c = a.marks.collections.builtin("starred")
        if not c.members:
            typer.echo("no starred files")
            return
        table(["PATH"], _member_rows(c))


@app.command()
def important(
    ctx: typer.Context,
    targets: Annotated[list[str] | None, typer.Argument(metavar="PATH-OR-DRIVE-ID...")] = None,
    group: Annotated[
        str | None,
        typer.Option(help='The group, e.g. "Houses/Hillside" (created as needed).'),
    ] = None,
    list_: Annotated[
        bool, typer.Option("--list", help="List the Important files instead.")
    ] = False,
) -> None:
    """Mark files or folders as ! Important (in --group; a file already in another
    group moves there), or list them with --list. Important files cannot be
    quarantined. Never moves or renames them."""
    if list_:
        if targets or group:
            print_error("error: --list takes no files and no --group")
            raise typer.Exit(EXIT_USER)
        with session(ctx, require_archive=False) as a:
            c = a.marks.collections.builtin("important")
            if not c.members:
                typer.echo("no important files")
                return
            table(["GROUP", "PATH"], _member_rows(c, _group_names(c)))
        return
    if not targets:
        print_error("error: name the files to mark, or use --list")
        raise typer.Exit(EXIT_USER)
    with session(ctx, write=True) as a:
        ids = [a.browse.resolve(t).drive_id for t in targets]
        a.marks.mark_important(ids, group)
        where = f" in {group.strip()}" if group and group.strip() else ""
        typer.echo(f"marked {len(ids)} item(s) Important{where}")


@app.command()
def unimportant(ctx: typer.Context, targets: TARGETS) -> None:
    """Take the ! Important mark off files or folders."""
    with session(ctx, write=True) as a:
        ids = [a.browse.resolve(t).drive_id for t in targets]
        a.marks.unmark_important(ids)
        typer.echo(f"unmarked {len(ids)} item(s)")


@ongoing_app.command("sync")
def ongoing_sync(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would happen.")
    ] = False,
) -> None:
    """Bring ##. Ongoing (the collections and the ★ files) and ##. Important (the !
    files) in line with the database (as dam serve does after a scan).

    Refused while the app has the archive open (it keeps these folders in line itself).
    """
    with session(ctx, write=not dry_run) as a:
        result = a.ongoing.sync(dry_run=dry_run)
        show_ops(result.plan)
        if dry_run:
            typer.echo("dry run: nothing was changed")
        for problem in result.problems:
            print_error(f"problem: {problem}")
        for batch in result.batches:  # one per root that changed something
            finish(batch)
        if result.problems:
            raise typer.Exit(EXIT_BATCH)


@ongoing_app.command("entries")
def ongoing_entries(ctx: typer.Context) -> None:
    """The top-level entries of ##. Ongoing: managed by a collection, or convertible."""
    with session(ctx) as a:
        entries = a.convert.entries()
        if not entries:
            typer.echo("##. Ongoing is empty")
            return
        table(
            ["NAME", "KIND", "TARGET", "STATUS"],
            [
                [
                    PurePosixPath(e.rel).name,
                    e.kind,
                    e.target_rel or "-",
                    "managed" if e.managed else (e.problem or "can be converted"),
                ]
                for e in entries
            ],
        )
