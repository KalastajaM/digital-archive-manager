"""The Typer apps, the global options and the helpers every command uses (dam.cli.main)."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Annotated

import typer

from dam.app import App
from dam.config import AppPaths
from dam.core.paths import OutsideArchiveError
from dam.errors import InvalidRequest, NotConfigured, NotFound
from dam.logging_setup import configure_logging, log_internal_error
from dam.ops.model import BatchResult, GuardError, OpFailed, OpKind, ResolvedOp
from dam.profiles import Locked, ProfileStore, ServeLock

EXIT_USER, EXIT_INTERNAL, EXIT_BATCH = 1, 3, 4
USER_ERRORS = (NotFound, InvalidRequest, GuardError, OutsideArchiveError, OpFailed)

app = typer.Typer(help="Digital Archive Manager", no_args_is_help=True, add_completion=False)
ongoing_app = typer.Typer(help="The ##. Ongoing folder (collections are published there).")
app.add_typer(ongoing_app, name="ongoing", no_args_is_help=True)


def print_error(message: str) -> None:
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
        print_error(f"error: {e}")
        raise typer.Exit(EXIT_USER) from None
    ctx.meta["dam.profile"] = chosen
    # every other command works on the folder of the chosen archive
    ctx.obj = chosen.data_dir


def store_of(ctx: typer.Context) -> ProfileStore:
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
            print_error(f"error: {e}")
        else:
            where = f" on port {e.port}" if e.port else ""
            print_error(
                f"error: This archive is open in the app{where}. {in_app}, or close the app first."
            )
        raise typer.Exit(EXIT_USER) from None
    except InvalidRequest as e:
        print_error(f"error: {e}")
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
                print_error("warning: interrupted operations found; run `dam recover` first.")
            yield application
        except (typer.Exit, typer.Abort):
            raise
        except NotConfigured as e:
            print_error(str(e))
            raise typer.Exit(EXIT_USER) from None
        except USER_ERRORS as e:
            print_error(f"error: {e}")
            raise typer.Exit(EXIT_USER) from None
        except Exception as e:
            log_path = log_internal_error(AppPaths(ctx.obj).logs_dir)
            print_error(f"internal error: {type(e).__name__}: {e} (details in {log_path})")
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
        print_error(
            f"failed: {result.failed.kind.value} {result.failed.src} -> {result.failed.dst}"
        )
    if result.error:
        problem = True
        print_error(f"error: {result.error}")
    if result.index_error:
        problem = True
        print_error(f"index error: {result.index_error} (the next `dam scan` repairs the index)")
    if tag_error:
        problem = True
        print_error(
            f"tagging failed: {tag_error}. Not tagged: {', '.join(untagged)}. "
            "The files were filed; add the tags again."
        )
    if cleanup_error:
        problem = True
        print_error(
            f"files restored, but removing the items/collection entries/notes the batch "
            f"created failed: {cleanup_error}"
        )
    if problem:
        raise typer.Exit(EXIT_BATCH)
