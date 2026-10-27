"""Setting up: init, add and openapi (dam.cli.main)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from dam import layouts as dam_layouts
from dam import setup as dam_setup
from dam.api import create_api
from dam.cli import newarchive
from dam.cli.main.common import (
    EXIT_USER,
    app,
    changing,
    finish,
    print_error,
    session,
    show_ops,
    store_of,
)
from dam.config import AppPaths
from dam.errors import InvalidRequest
from dam.logging_setup import configure_logging
from dam.services.layout import layout_label


def _show_special_folders(root: Path) -> None:
    typer.echo("\nThe app uses these folders inside it when they exist:")
    for f in dam_setup.special_folder_status(root):
        mark = "found" if f["exists"] else "not there yet"
        typer.echo(f"  {f['name']}  ({f['title'].lower()}: {f['purpose']}) {mark}")


def _pick(title: str, options: list[str], extra: list[str]) -> int:
    """Show ``options`` then ``extra`` as 1..n; returns the 0-based index of the choice
    in the combined list. Asks again on a bad answer."""
    typer.echo(title)
    labels = [*options, *extra]
    for i, label in enumerate(labels, 1):
        typer.echo(f"  {i}. {label}")
    while True:
        answer = typer.prompt("Number", default="", show_default=False).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(labels):
            return int(answer) - 1
        print_error(f"Enter a number from 1 to {len(labels)}.")


Guard = Callable[[Path], str | None]


def _ask_checked(
    app_paths: AppPaths, raw: str, guard: Guard | None = None
) -> dam_setup.PathCheck | None:
    """Check ``raw``; a folder that is missing can be created after a yes (its parent
    must exist). Returns the passing check, or None after saying what is wrong."""
    check = dam_setup.check_archive_path(raw, app_paths, guard=guard)
    if check.can_create and check.path is not None:
        if typer.confirm(f"{check.path} does not exist. Create it?", default=False):
            dam_setup.create_archive_folder(check)
            check = dam_setup.check_archive_path(raw, app_paths, guard=guard)
    if not check.ok:
        print_error(f"{check.message}" + (f" ({check.path})" if check.path else ""))
        return None
    return check


def _choose_interactively(app_paths: AppPaths, guard: Guard | None = None) -> Path:
    candidates = dam_setup.detect_candidates()
    other = "Another folder on this computer (type its path)"
    while True:
        typer.echo("Where should your archive live?\n")
        if not candidates:
            typer.echo("No cloud-drive folders were found.")
        i = _pick(
            "Found on this computer:" if candidates else "",
            [f"{c.label}  {c.path}" for c in candidates],
            [other],
        )
        if i >= len(candidates):
            raw = typer.prompt("Full path of the folder to use as the archive")
            check = _ask_checked(app_paths, raw, guard)
            if check is not None and check.path is not None:
                return check.path
            continue
        base = candidates[i].path
        subs = dam_setup.list_subfolders(base)
        j = _pick(
            f"\nInside {base}, which folder is the archive?",
            [f"{name}/" for name in subs],
            [f"Use {base.name or base} itself", "Create a new folder here"],
        )
        if j < len(subs):
            chosen = base / subs[j]
        elif j == len(subs):
            chosen = base
        else:
            name = typer.prompt("Name of the new folder", default="Digital Archive").strip()
            if not name or "/" in name or "\\" in name or name in (".", ".."):
                print_error("Use a plain folder name (no slashes).")
                continue
            chosen = base / name
        check = _ask_checked(app_paths, str(chosen), guard)
        if check is not None and check.path is not None:
            return check.path


@app.command()
def init(
    ctx: typer.Context,
    archive: Annotated[
        Path | None,
        typer.Option("--archive", help="The archive folder to use (skips the questions)."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Do not ask before writing the setting.")
    ] = False,
    layout: Annotated[
        str | None,
        typer.Option(
            "--layout",
            help="Start a new archive with this starter layout (household, minimal, empty) "
            "or `none`. Only folders that do not exist yet are made.",
        ),
    ] = None,
    numbered: Annotated[
        bool,
        typer.Option(
            "--numbered/--no-numbered", help="Number the layout's folders (10. Finance, ...)."
        ),
    ] = True,
) -> None:
    """Choose the archive folder (first-run setup), and optionally start a new archive.

    Looks for cloud-drive folders (Google Drive, OneDrive, Dropbox, iCloud Drive, ...),
    lets you pick one and the folder inside it, and writes `archive_root` to
    <data dir>/config/settings.yaml after you confirm. If the folder is empty you are
    offered "Start a new archive here": a starter layout (Household, Minimal, Empty) plus
    the special folders, previewed first and made as one undoable batch (`dam undo`).
    Nothing else is changed, and no folder is made that you did not confirm.
    """
    with changing(ctx):
        _init(ctx, archive, yes, layout, numbered)


def _init(
    ctx: typer.Context,
    archive: Path | None,
    yes: bool,
    layout: str | None,
    numbered: bool,
) -> None:
    app_paths = AppPaths(ctx.obj)
    spec: dam_layouts.Spec | None = None
    # another archive's folder (or one inside / around it) cannot be this one's
    guard = store_of(ctx).root_guard(ctx.meta["dam.profile"].id)
    try:
        app_paths.ensure()
        configure_logging(app_paths)
        current = dam_setup.current_archive_root(app_paths)
        if archive is not None:
            check = dam_setup.check_archive_path(str(archive), app_paths, guard=guard)
            if (
                check.can_create
                and check.path is not None
                and (
                    yes or typer.confirm(f"{check.path} does not exist. Create it?", default=False)
                )
            ):
                dam_setup.create_archive_folder(check)
                check = dam_setup.check_archive_path(str(archive), app_paths, guard=guard)
            if not check.ok or check.path is None:
                print_error(f"error: {check.message}")
                raise typer.Exit(EXIT_USER)
            chosen = check.path
        else:
            if current:
                typer.echo(f"The archive folder is already set: {current}")
                if not typer.confirm("Choose a different one?", default=False):
                    return
            chosen = _choose_interactively(app_paths, guard)
        already = bool(current) and Path(current).expanduser() == chosen
        if already and layout is None and not dam_setup.is_empty_folder(chosen):
            typer.echo(f"Already set to {chosen}; nothing to change.")
            _show_special_folders(chosen)
            return
        spec = newarchive.choose_layout(chosen, layout, numbered, yes)
        if spec is not None:
            newarchive.preview_text(spec, chosen)
            if not yes and not typer.confirm("Make these folders?", default=True):
                typer.echo("Nothing written.")
                raise typer.Exit(EXIT_USER)
        elif already:
            typer.echo(f"Already set to {chosen}; nothing to change.")
            _show_special_folders(chosen)
            return
        target = dam_setup.settings_path(app_paths)
        if not already:
            typer.echo(f"\nThis will write to {target}:\n  {dam_setup.planned_line(chosen)}")
            if current:
                typer.echo(f"  (replacing: {current})")
            if not yes and not typer.confirm("Write it?", default=True):
                typer.echo("Nothing written.")
                raise typer.Exit(EXIT_USER)
        if spec is not None:
            template = dam_layouts.find_template(spec.template_id, dam_layouts.load_templates())
            names = dam_layouts.build_folders(spec)
            dam_setup.write_layout_settings(
                app_paths, spec.special, dam_layouts.ai_exclude_folders(template, names)
            )
        if not already:
            dam_setup.write_archive_root(app_paths, chosen)
    except (typer.Exit, typer.Abort):
        raise
    except (OSError, dam_layouts.LayoutError, InvalidRequest) as e:
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"Saved. The archive folder is {chosen}")
    if spec is not None:
        with session(ctx, warn_pending=False, write=True) as a:
            outcome = a.layout.apply(spec, origin="cli")
            finish(outcome.batch)
            typer.echo(
                f"{layout_label(outcome.created)}. Undo it with: dam undo {outcome.batch.batch_id}"
            )
            if outcome.rules_written:
                typer.echo("Example filing rules for these folders were saved to config/rules.")
    _show_special_folders(chosen)
    typer.echo("\nNext: `dam serve` opens the app.")


@app.command()
def add(
    ctx: typer.Context,
    files: Annotated[list[Path], typer.Argument(metavar="FILE...", exists=True, dir_okay=False)],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would happen.")
    ] = False,
) -> None:
    """Copy files into the inbox (the originals stay where they are).

    A name that is taken gets _2; nothing is overwritten. Each file may be up to 200 MB.
    One journaled batch: `dam undo <batch>` moves the copies to the quarantine folder.
    """
    with session(ctx, write=not dry_run) as a:
        ops = a.intake.preview(list(files))
        show_ops(ops)
        if dry_run:
            typer.echo("dry run: nothing was changed")
            return
        if not yes and not typer.confirm(f"Copy {len(files)} file(s) into the inbox?"):
            typer.echo("Nothing copied.")
            raise typer.Exit(1)
        result = a.intake.add_files(list(files))
        finish(result)
        if result.done:
            typer.echo(f"Undo with: dam undo {result.batch_id}")


@app.command()
def openapi(ctx: typer.Context) -> None:
    """Print the HTTP API's OpenAPI schema as JSON."""
    with session(ctx, warn_pending=False, require_archive=False) as a:
        typer.echo(json.dumps(create_api(a).openapi(), indent=2))
