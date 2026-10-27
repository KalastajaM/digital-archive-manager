"""Commands on the archive and its index: scan, index, errors, inbox, file, search, quarantine,
move, activity, undo and recover (dam.cli.main)."""

import time
from typing import Annotated

import typer

from dam.cli.main.common import EXIT_BATCH, app, finish, print_error, session, show_ops, table
from dam.ops.model import OpKind
from dam.services.inbox import FileItResult, FileRequest


@app.command()
def scan(ctx: typer.Context) -> None:
    """Sync the file index with the archive."""
    with session(ctx, write=True) as a:
        r = a.scan()
        typer.echo(
            f"added {r.added}, moved {r.moved}, updated {r.updated}, "
            f"missing {r.missing}, rekeyed {r.rekeyed}"
        )


@app.command()
def index(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Index at most this many files.")] = None,
) -> None:
    """Index file contents (text extraction, OCR) until nothing is left."""
    with session(ctx, write=True) as a:
        typer.echo(f"indexed {a.index(limit)} file(s)")


@app.command()
def errors(
    ctx: typer.Context,
    retry: Annotated[
        bool,
        typer.Option("--retry", help="Queue the listed error files for indexing again."),
    ] = False,
    all_: Annotated[
        bool, typer.Option("--all", help="Also list unsupported files (with why).")
    ] = False,
    retry_unsupported: Annotated[
        bool,
        typer.Option(
            "--retry-unsupported",
            help="Queue the listed unsupported files for indexing again (implies --all).",
        ),
    ] = False,
) -> None:
    """List the files whose content could not be indexed, and why."""
    all_ = all_ or retry_unsupported
    with session(ctx, write=retry or retry_unsupported) as a:
        problems = a.repo.index_problems(include_unsupported=all_)
        if not problems:
            typer.echo("no index errors" if not all_ else "no index errors or unsupported files")
            return
        table(
            ["STATE", "PATH", "REASON"],
            [[p.state, p.path, p.reason or "-"] for p in problems],
        )
        if retry or retry_unsupported:
            # --retry: error rows only (an unsupported type stays unsupported);
            # --retry-unsupported: the unsupported ones too
            states = {"error"} if retry else set()
            if retry_unsupported:
                states.add("unsupported")
            queued = a.retry_index([p.drive_id for p in problems if p.state in states])
            typer.echo(
                f"queued {queued} file(s) for indexing again "
                "(`dam index` now, or the running `dam serve` picks them up)"
            )


@app.command()
def inbox(ctx: typer.Context) -> None:
    """List the files waiting in the inbox, with suggestions."""
    with session(ctx) as a:
        entries = a.inbox.list()
        if not entries:
            typer.echo("inbox is empty")
            return
        table(
            ["NAME", "SUGGESTED NAME", "SUGGESTED FOLDER", "SOURCES"],
            [
                [
                    e.record.name or "",
                    e.suggestion.name,
                    e.suggestion.folder or "-",
                    ", ".join(e.suggestion.sources) or "-",
                ]
                for e in entries
            ],
        )


@app.command("file")
def file_cmd(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(metavar="PATH-OR-DRIVE-ID")],
    folder: Annotated[str, typer.Option(help="Destination folder (archive-relative).")],
    name: Annotated[str | None, typer.Option(help="New name (default: the suggestion).")] = None,
    tag: Annotated[list[str] | None, typer.Option(help="Tag to add (repeatable).")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would happen.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Rename, move and tag one file (shows the plan and asks first)."""
    with session(ctx, write=not dry_run) as a:
        drive_id = a.browse.resolve(target).drive_id
        final_name = name if name is not None else a.inbox.suggestion(drive_id).name
        reqs = [FileRequest(drive_id, final_name, folder, tags=list(tag or []))]
        show_ops(a.inbox.preview(reqs, origin="cli"), reqs[0].tags)
        if dry_run:
            typer.echo("dry run: nothing was changed")
            return
        if not yes and not typer.confirm("Apply?"):
            print_error("aborted")
            raise typer.Exit(1)
        outcome: FileItResult = a.inbox.file_it(reqs, origin="cli")
        finish(outcome.batch, outcome.tag_error, outcome.untagged)


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument()],
    folder: Annotated[str | None, typer.Option(help="Limit to this folder.")] = None,
    limit: Annotated[int, typer.Option(help="Maximum number of hits.")] = 50,
) -> None:
    """Full-text search."""
    with session(ctx) as a:
        hits = a.search(query, folder=folder, limit=limit)
        if not hits:
            typer.echo("no matches")
            return
        table(["PATH", "SNIPPET"], [[h.path, " ".join(h.snippet.split())] for h in hits])


@app.command()
def quarantine(
    ctx: typer.Context,
    targets: Annotated[list[str], typer.Argument(metavar="PATH-OR-DRIVE-ID...")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would happen.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Move files into the quarantine folder (never deletes)."""
    with session(ctx, write=not dry_run) as a:
        ids = [a.browse.resolve(t).drive_id for t in targets]
        preview = a.browse.quarantine(ids, origin="cli", dry_run=True)
        show_ops(preview.done)
        if preview.failed is not None or preview.error:
            finish(preview)  # prints the problem and exits 4 before any confirmation
        if dry_run:
            typer.echo("dry run: nothing was changed")
            return
        if not yes and not typer.confirm(f"Quarantine {len(ids)} item(s)?"):
            print_error("aborted")
            raise typer.Exit(1)
        finish(a.browse.quarantine(ids, origin="cli"))


@app.command()
def move(
    ctx: typer.Context,
    targets: Annotated[list[str], typer.Argument(metavar="PATH-OR-DRIVE-ID...")],
    folder: Annotated[str, typer.Option(help="Destination folder (archive-relative).")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would happen.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Move files into another archive folder, names kept (shows the plan and asks first).

    Files only; not from or into ##. Ongoing, nor into ##. To Delete (use `dam quarantine`).
    Undo with `dam undo BATCH`.
    """
    with session(ctx, write=not dry_run) as a:
        records = [a.browse.resolve(t) for t in targets]
        ids = [r.drive_id for r in records]
        preview = a.browse.move(ids, folder, origin="cli", dry_run=True)
        show_ops(preview.done)
        paths = {r.drive_id: r.path for r in records}
        for drive_id in preview.unchanged:
            typer.echo(f"already in {preview.folder}: {paths[drive_id]}")
        if dry_run:
            typer.echo("dry run: nothing was changed")
            return
        moves = sum(op.kind is OpKind.MOVE for op in preview.done)
        if not moves:
            return
        if not yes and not typer.confirm(f"Move {moves} file(s)?"):
            print_error("aborted")
            raise typer.Exit(1)
        finish(a.browse.move(ids, folder, origin="cli"))


@app.command()
def activity(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="Number of batches to show.")] = 20,
) -> None:
    """Recent batches of operations."""
    with session(ctx) as a:
        batches = a.activity.recent(limit)
        if not batches:
            typer.echo("no activity")
            return
        rows = []
        for b in batches:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b.created))
            status = "undo" if b.is_undo else "undone" if b.undone else ""
            first = b.ops[0]
            summary = f"{first.kind} {first.src or ''} -> {first.dst or ''}"
            if len(b.ops) > 1:
                summary += f" (+{len(b.ops) - 1} more)"
            rows.append([b.batch_id, when, b.origin, str(len(b.ops)), status, summary])
        table(["BATCH", "WHEN", "ORIGIN", "OPS", "STATUS", "FIRST OP"], rows)


@app.command()
def undo(
    ctx: typer.Context,
    batch_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Revert a batch."""
    with session(ctx, write=True) as a:
        summary = a.activity.get(batch_id)  # unknown batch: NotFound, before asking
        if not yes:
            for op in summary.ops:
                typer.echo(f"{op.state:<10} {op.kind} {op.src or ''} -> {op.dst or ''}")
        if not yes and not typer.confirm(f"Undo batch {batch_id}?"):
            print_error("aborted")
            raise typer.Exit(1)
        outcome = a.activity.undo(batch_id)
        finish(outcome.batch, cleanup_error=outcome.follow_up_error)


@app.command()
def recover(ctx: typer.Context) -> None:
    """Settle operations that were interrupted (reads the disk; archive files are never
    changed, but an interrupted rule picture move may be finished)."""
    with session(ctx, warn_pending=False, write=True, in_app="Use Run recovery there") as a:
        r = a.activity.recover()
        if not r.entries and not r.index_errors:
            typer.echo("nothing to recover")
            return
        for e in r.entries:
            detail = f"  ({e.error})" if e.error else ""
            typer.echo(f"{e.state:<10} {e.kind} {e.src or ''} -> {e.dst or ''}{detail}")
        for msg in r.index_errors:
            print_error(f"index error: {msg}")
        if r.index_errors:
            raise typer.Exit(EXIT_BATCH)
