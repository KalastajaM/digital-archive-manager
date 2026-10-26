"""The ``dam`` command line. A thin interface: every command only calls ``App`` services.

Exit codes: 0 success; 1 user error (unknown file, invalid request, guard refusal);
2 command line usage error (click); 3 internal error (traceback goes to the log file);
4 a batch problem (``failed``, ``error``, ``index_error`` or a tag error).
"""

import json
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

import typer

from dam import layouts as dam_layouts
from dam import serve as dam_serve
from dam import setup as dam_setup
from dam.api import create_api
from dam.app import App
from dam.cli import newarchive
from dam.config import AppPaths, load_settings
from dam.core.paths import OutsideArchiveError
from dam.logging_setup import configure_logging, log_internal_error
from dam.ops.model import BatchResult, GuardError, OpFailed, OpKind, ResolvedOp
from dam.profiles import Locked, Profile, ProfileStore, ServeLock
from dam.reminders import launchd, notify
from dam.reminders.engine import Due
from dam.services.archives import ArchiveService
from dam.services.errors import InvalidRequest, NotConfigured, NotFound
from dam.services.inbox import FileItResult, FileRequest
from dam.services.layout import layout_label

EXIT_USER, EXIT_INTERNAL, EXIT_BATCH = 1, 3, 4
USER_ERRORS = (NotFound, InvalidRequest, GuardError, OutsideArchiveError, OpFailed)

app = typer.Typer(help="Digital Archive Manager", no_args_is_help=True, add_completion=False)
ongoing_app = typer.Typer(help="The ##. Ongoing folder (collections are published there).")
app.add_typer(ongoing_app, name="ongoing", no_args_is_help=True)


def _err(message: str) -> None:
    typer.echo(message, err=True)


archives_app = typer.Typer(
    help="Several archives (profiles): each has its own settings, index and logs."
)
app.add_typer(archives_app, name="archives", no_args_is_help=True)


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir", help="Data directory (default: DAM_DATA_DIR or the standard one)."
        ),
    ] = None,
    archive: Annotated[
        str | None,
        typer.Option(
            "--archive",
            envvar="DAM_ARCHIVE",
            help="The archive (profile) to use, by name or id (default: the one in use; "
            "see `dam archives list`).",
        ),
    ] = None,
) -> None:
    store = ProfileStore(data_dir)
    ctx.meta["dam.store"] = store
    if ctx.invoked_subcommand == "archives":
        ctx.obj = None  # the archives commands pick their own profiles
        ctx.meta["dam.archive_option"] = archive
        return
    try:
        profiles = store.load(persist=True)  # adopts an existing single-archive folder
        chosen = store.find(archive, profiles) if archive else next(p for p in profiles if p.active)
    except (NotFound, InvalidRequest) as e:
        _err(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    ctx.meta["dam.profile"] = chosen
    # every other command works on the folder of the chosen archive
    ctx.obj = chosen.data_dir


def _store(ctx: typer.Context) -> ProfileStore:
    return ctx.meta["dam.store"]


def _command_name(ctx: typer.Context) -> str:
    """``dam file``, ``dam ongoing sync``: the command as typed, without its options."""
    names: list[str] = []
    c: typer.Context | None = ctx
    while c is not None and c.parent is not None:
        names.append(c.info_name or "")
        c = c.parent
    return " ".join(["dam", *reversed(names)])


@contextmanager
def changing(ctx: typer.Context, in_app: str = "Do this there") -> Iterator[None]:
    """Hold the archive's lock (``serve.lock``, the one ``dam serve`` holds) while a
    command changes it, so the app and other commands never write at the same time.
    Re-entrant in one process (``init`` opens a session inside its own hold). Refused:
    exit 1 saying who has it; ``in_app`` says what to do when that is the app."""
    data_dir = Path(ctx.obj)
    held: dict[Path, ServeLock] = ctx.meta.setdefault("dam.held", {})
    if data_dir in held:
        yield
        return
    lock = ServeLock(data_dir)
    try:
        lock.acquire(command=_command_name(ctx))
    except Locked as e:
        if e.command:
            _err(f"error: {e}")
        else:
            where = f" on port {e.port}" if e.port else ""
            _err(
                f"error: This archive is open in the app{where}. {in_app}, or close the app first."
            )
        raise typer.Exit(EXIT_USER) from None
    except InvalidRequest as e:
        _err(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    held[data_dir] = lock
    try:
        yield
    finally:
        del held[data_dir]
        lock.release()


@contextmanager
def session(
    ctx: typer.Context,
    warn_pending: bool = True,
    require_archive: bool = True,
    write: bool = False,
    in_app: str = "Do this there",
) -> Iterator[App]:
    """Open the App for one command and always close it. ``write``: the command changes
    the archive, its database or its settings, so it holds the archive's lock first
    (``changing``; ``in_app`` is its hint when the app has the archive).

    Known user errors exit 1 with ``error: <message>``; anything else exits 3 with one
    line on stderr and the traceback in the log file. Every command logs to
    ``<data dir>/logs/dam.log`` (INFO) and stderr (WARNING).
    """
    with changing(ctx, in_app) if write else nullcontext():
        application: App | None = None
        try:
            configure_logging(AppPaths(ctx.obj))
            application = App.create(ctx.obj, require_archive=require_archive)
            if warn_pending and application.activity.pending() and _alone(ctx):
                _err("warning: interrupted operations found; run `dam recover` first.")
            yield application
        except (typer.Exit, typer.Abort):
            raise
        except NotConfigured as e:
            _err(str(e))
            raise typer.Exit(EXIT_USER) from None
        except USER_ERRORS as e:
            _err(f"error: {e}")
            raise typer.Exit(EXIT_USER) from None
        except Exception as e:
            log_path = log_internal_error(AppPaths(ctx.obj).logs_dir)
            _err(f"internal error: {type(e).__name__}: {e} (details in {log_path})")
            raise typer.Exit(EXIT_INTERNAL) from None
        finally:
            if application is not None:
                application.close()


def _alone(ctx: typer.Context) -> bool:
    """Whether no other process (the app, another command) has this archive: only then
    are pending journal rows surely interrupted ones, not rows of a change under way.
    The app offers its own Run recovery."""
    data_dir = Path(ctx.obj)
    return data_dir in ctx.meta.get("dam.held", {}) or ServeLock.holder(data_dir) is None


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(c) for c in col) for col in zip(headers, *rows, strict=True)]
    for row in (headers, *rows):
        typer.echo("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())


def show_ops(ops: list[ResolvedOp], tags: list[str] | None = None) -> None:
    if not ops:
        typer.echo("no file changes")
    for op in ops:
        note = f"  ({op.note})" if op.note else ""
        src = op.src.removeprefix("abs:") if op.kind is OpKind.COPY and op.src else op.src
        typer.echo(f"{op.kind.value:<10} {src} -> {op.dst}{note}")
    if tags:
        typer.echo(f"tags: {', '.join(tags)}")


def finish(
    result: BatchResult,
    tag_error: str | None = None,
    untagged: list[str] = (),
    cleanup_error: str | None = None,
) -> None:
    """Print what was done; exit 4 if the batch, the tagging or the undo's cleanup did
    not complete cleanly."""
    if not result.dry_run and (result.done or result.failed or result.error or result.index_error):
        typer.echo(f"batch {result.batch_id}: {len(result.done)} operation(s) done")
    problem = False
    if result.failed is not None:
        problem = True
        _err(f"failed: {result.failed.kind.value} {result.failed.src} -> {result.failed.dst}")
    if result.error:
        problem = True
        _err(f"error: {result.error}")
    if result.index_error:
        problem = True
        _err(f"index error: {result.index_error} (the next `dam scan` repairs the index)")
    if tag_error:
        problem = True
        _err(
            f"tagging failed: {tag_error}. Not tagged: {', '.join(untagged)}. "
            "The files were filed; add the tags again."
        )
    if cleanup_error:
        problem = True
        _err(
            f"files restored, but removing the items/collection entries/notes the batch "
            f"created failed: {cleanup_error}"
        )
    if problem:
        raise typer.Exit(EXIT_BATCH)


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
            _err("aborted")
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
            _err("aborted")
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
            _err("aborted")
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
            _err("aborted")
            raise typer.Exit(1)
        outcome = a.activity.undo(batch_id)
        finish(outcome.batch, cleanup_error=outcome.follow_up_error)


@app.command()
def recover(ctx: typer.Context) -> None:
    """Settle operations that were interrupted (reads the disk, never changes files)."""
    with session(ctx, warn_pending=False, write=True, in_app="Use Run recovery there") as a:
        r = a.activity.recover()
        if not r.entries and not r.index_errors:
            typer.echo("nothing to recover")
            return
        for e in r.entries:
            detail = f"  ({e.error})" if e.error else ""
            typer.echo(f"{e.state:<10} {e.kind} {e.src or ''} -> {e.dst or ''}{detail}")
        for msg in r.index_errors:
            _err(f"index error: {msg}")
        if r.index_errors:
            raise typer.Exit(EXIT_BATCH)


@app.command()
def serve(
    ctx: typer.Context,
    port: Annotated[int | None, typer.Option(help="Port (default from settings).")] = None,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open the browser.")] = False,
) -> None:
    """Start the web UI on 127.0.0.1 (scans, watches and indexes in the background).

    Ctrl+C (SIGINT) or SIGTERM stops it cleanly: exit 0 and "stopped" on stderr.
    Without a built frontend it says so on stderr and serves only the API.
    Without a configured archive folder it starts in setup mode: the browser shows a
    first-run screen where you choose the folder (or run `dam init` instead).
    """
    app_paths = AppPaths(ctx.obj)
    app_paths.ensure()
    built = (dam_serve.STATIC_DIR / "index.html").is_file()
    store, profile = _store(ctx), ctx.meta["dam.profile"]
    problem = store.root_problems().get(profile.id)
    if problem:
        _err(f"error: the archive '{profile.name}' cannot be opened: {problem}")
        raise typer.Exit(EXIT_USER)
    # one process serves a profile at a time (several profiles can run side by side)
    lock = ServeLock(app_paths.data_dir)
    try:
        lock.acquire()
    except Locked as e:
        _err(f"error: '{profile.name}': {e}")
        raise typer.Exit(EXIT_USER) from None
    host = dam_serve.Host(store, dam_serve.STATIC_DIR)
    host.profile_id, host.first_lock = profile.id, lock
    archives = ArchiveService(store, profile.id, host, app_paths)
    try:
        if not dam_setup.is_configured(app_paths):
            configure_logging(app_paths)
            try:
                settings = load_settings(app_paths)
            except Exception as e:
                _err(f"error: cannot read {dam_setup.settings_path(app_paths)}: {e}")
                raise typer.Exit(EXIT_USER) from None
            chosen = port if port is not None else settings.server_port
            if not built:
                _err("frontend not built — run `cd frontend && npm ci && npm run build`")
                _err(dam_setup.NOT_CONFIGURED)
                raise typer.Exit(EXIT_USER)
            lock.publish(chosen)
            typer.echo(f"No archive folder configured yet: setup is on http://127.0.0.1:{chosen}/")
            typer.echo("(or press Ctrl+C and run `dam init` instead)")
            try:
                dam_serve.serve_setup(
                    app_paths,
                    dam_serve.STATIC_DIR,
                    chosen,
                    open_browser=not no_open,
                    host=host,
                    archives=archives,
                )
            except USER_ERRORS as e:
                _err(f"error: {e}")
                raise typer.Exit(EXIT_USER) from None
            _err("stopped")
            return
        with session(ctx, warn_pending=False) as a:
            if a.activity.pending():  # `dam recover` is refused while this serves
                _err("warning: interrupted operations found; use Run recovery in the app.")
            port = port if port is not None else a.settings.server_port
            if not built:  # the API still works; a browser would only show a 404
                _err("frontend not built — run `cd frontend && npm ci && npm run build`")
            lock.publish(port)
            name = f" ({profile.name})" if len(store.load()) > 1 else ""
            typer.echo(f"serving on http://127.0.0.1:{port}/{name} (Ctrl+C to stop)")
            api = create_api(a, dam_serve.STATIC_DIR, archives)
            dam_serve.serve(a, api, port, open_browser=built and not no_open, host=host)
            _err("stopped")
    finally:
        lock.release()


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
        _err(f"Enter a number from 1 to {len(labels)}.")


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
        _err(f"{check.message}" + (f" ({check.path})" if check.path else ""))
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
                _err("Use a plain folder name (no slashes).")
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
    guard = _store(ctx).root_guard(ctx.meta["dam.profile"].id)
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
                _err(f"error: {check.message}")
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
        _err(f"error: {e}")
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
    store: ProfileStore = _store(ctx)
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
        _err(_schedule_help(ctx, a))
        raise typer.Exit(EXIT_USER)
    label, archive = _reminder_target(ctx)
    path, hour = launchd.plist_path(label), a.settings.reminders.hour
    cmd = launchd.dam_command()
    typer.echo(f"LaunchAgent {path}:")
    typer.echo(launchd.plist(cmd, a.app_paths.data_dir, hour, label, archive))
    if not yes and not typer.confirm(f"Write {path} and load it?"):
        _err("aborted")
        raise typer.Exit(EXIT_USER)
    try:
        launchd.install(cmd, a.app_paths.data_dir, hour, force=force, label=label, archive=archive)
    except launchd.LaunchdError as e:
        _err(f"error: {e}")
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
        _err("aborted")
        raise typer.Exit(EXIT_USER)
    try:
        launchd.uninstall(label=label)
    except launchd.LaunchdError as e:
        _err(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"removed {path}")


def _set_email_password(a: App) -> None:
    email = a.settings.reminders.email
    if email is None:
        _err("error: set reminders.email (to, smtp_host, smtp_user) in settings.yaml first")
        raise typer.Exit(EXIT_USER)
    password = typer.prompt(
        f"Password for {email.smtp_user} at {email.smtp_host}",
        hide_input=True,
        confirmation_prompt=True,
    )
    try:
        notify.store_keychain_password(email.smtp_user, password)
    except Exception as e:  # noqa: BLE001 - never echo the details (they may quote input)
        _err(f"error: could not store the password in the Keychain ({type(e).__name__})")
        raise typer.Exit(EXIT_USER) from None
    typer.echo(f"password for {email.smtp_user} stored in the Keychain")


def _test_notification(a: App, dry_run: bool) -> None:
    channels = [n.id for n in notify.enabled_notifiers(a.settings)]
    if not channels:
        _err("error: no reminder channel is enabled (reminders.mac / reminders.email)")
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
            _err(f"error: {channel}: {error}")
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
            _err(f"error: {channel}: {message}")
        if result.errors:
            raise typer.Exit(EXIT_BATCH)


# -- several archives (profiles) -----------------------------------------------------


@contextmanager
def _archive_errors() -> Iterator[None]:
    try:
        yield
    except (NotFound, InvalidRequest) as e:
        _err(f"error: {e}")
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
        store = _store(ctx)
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
    store = _store(ctx)
    if demo and folder is None:
        _err("error: --demo needs --folder (a new or empty folder for the demo archive)")
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
        profile = _store(ctx).set_active(name)
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
        profile = _store(ctx).set_name(old, new)
    typer.echo(f"Renamed to '{profile.name}' (id {profile.id}).")


@archives_app.command("color")
def archives_color(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name or id.")],
    color: Annotated[str, typer.Argument(help="Colour like #3b6fd4.")],
) -> None:
    """Change the colour an archive is shown with."""
    with _archive_errors():
        profile = _store(ctx).recolor(name, color)
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
        gone = _store(ctx).forget(name, switch_to)
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
        profile = _store(ctx).find(name)
    typer.echo(f"data folder:    {profile.data_dir}")
    typer.echo(f"archive folder: {profile.archive_root or '(not set up yet)'}")


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
        _err(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    except Exception as e:  # noqa: BLE001 - never echo the details (they may quote input)
        _err(f"error: could not store the key in the Keychain ({type(e).__name__})")
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
            _err(f"error: could not reach the Keychain ({type(e).__name__})")
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
            _err(f"warning: {e.file}: {e.message}")
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
            ["ID", "NAME", "MEMBERS", "GROUPS", "ONGOING", "STATUS"],
            [
                [
                    str(c.id),
                    name,
                    str(len(c.members)),
                    str(len(c.groups)),
                    c.ongoing_rel or "-",
                    c.ongoing_status or "",
                ]
                for c, name in zip(found, shown, strict=True)
            ],
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
            _err("error: --list takes no files and no --group")
            raise typer.Exit(EXIT_USER)
        with session(ctx, require_archive=False) as a:
            c = a.marks.collections.builtin("important")
            if not c.members:
                typer.echo("no important files")
                return
            table(["GROUP", "PATH"], _member_rows(c, _group_names(c)))
        return
    if not targets:
        _err("error: name the files to mark, or use --list")
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
            _err(f"problem: {problem}")
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
