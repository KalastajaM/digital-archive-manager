"""Trays and collections (dam.cli.main)."""

import time
from typing import Annotated

import typer

from dam.cli.main.common import app, print_error, session, table
from dam.reminders import notify


@app.command("trays")
def trays_cmd(
    ctx: typer.Context,
    tray: Annotated[str | None, typer.Option(help="Only this tray (its id).")] = None,
    done: Annotated[bool, typer.Option("--done", help="Done items instead of open.")] = False,
) -> None:
    """The items in each tray (open by default)."""
    state = "done" if done else "open"
    with session(ctx, require_archive=False) as a:
        for e in a.tray_errors:
            print_error(f"warning: {e.file}: {e.message}")
        names = {t.id: t.name for t in a.tray_defs}
        for tray_id in [tray] if tray is not None else list(names):
            items = a.trays.list(tray_id, state)
            typer.echo(f"{notify.plain(names.get(tray_id, tray_id))} ({len(items)} {state})")
            rows = []
            for i in items:
                when = (
                    time.strftime("%Y-%m-%d", time.localtime(i.done_at))
                    if done and i.done_at
                    else (i.date.isoformat() if i.date else "-")
                )
                flag = f"needs {', '.join(i.missing_required)}" if i.missing_required else ""
                rows.append([str(i.id), when, notify.plain(i.title), flag])
            if rows:
                table(["ID", "DONE" if done else "DATE", "TITLE", ""], rows)


@app.command("collections")
def collections_cmd(
    ctx: typer.Context,
    closed: Annotated[bool, typer.Option("--closed", help="Closed ones instead of open.")] = False,
) -> None:
    """The collections (open by default), as a tree: a child collection is indented
    under its parent. One whose parent is not listed (a closed child of an open parent,
    say) shows its full path instead."""
    with session(ctx, require_archive=False) as a:
        found = a.collections.list("closed" if closed else "open")
        if not found:
            typer.echo("no collections")
            return
        depth: dict[int, int] = {}
        shown: list[str] = []
        for c in found:  # tree order: a listed parent comes before its children
            if c.parent_id is None or c.parent_id not in depth:
                depth[c.id] = 0
                shown.append(" › ".join(c.path))
            else:
                depth[c.id] = depth[c.parent_id] + 1
                shown.append("  " * depth[c.id] + c.name)
        table(
            ["ID", "NAME", "MEMBERS", "ONGOING", "STATUS"],
            [
                [
                    str(c.id),
                    name,
                    str(len(c.members)),
                    c.ongoing_rel or "-",
                    c.ongoing_status or "",
                ]
                for c, name in zip(found, shown, strict=True)
            ],
        )
