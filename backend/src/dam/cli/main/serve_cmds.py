"""Running the app: serve and open (dam.cli.main)."""

import webbrowser
from typing import Annotated

import typer

from dam import serve as dam_serve
from dam import setup as dam_setup
from dam.api import create_api
from dam.api.auth import auth_url, load_token, read_token
from dam.cli.main.common import EXIT_USER, USER_ERRORS, app, print_error, session, store_of
from dam.config import AppPaths, load_settings
from dam.logging_setup import configure_logging
from dam.profiles import Locked, Profile, ProfileStore, ServeLock
from dam.services.archives import ArchiveService


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
    The browser is opened on a sign-in link (only a signed-in browser can use the app);
    with --no-open the link is printed instead.
    """
    app_paths = AppPaths(ctx.obj)
    app_paths.ensure()
    built = (dam_serve.STATIC_DIR / "index.html").is_file()
    store, profile = store_of(ctx), ctx.meta["dam.profile"]
    problem = store.root_problems().get(profile.id)
    if problem:
        print_error(f"error: the archive '{profile.name}' cannot be opened: {problem}")
        raise typer.Exit(EXIT_USER)
    # one process serves a profile at a time (several profiles can run side by side)
    lock = ServeLock(app_paths.data_dir)
    try:
        lock.acquire()
    except Locked as e:
        print_error(f"error: '{profile.name}': {e}")
        raise typer.Exit(EXIT_USER) from None
    host = dam_serve.Host(store, dam_serve.STATIC_DIR)
    host.profile_id, host.first_lock = profile.id, lock
    token = load_token(store.base)
    archives = ArchiveService(store, profile.id, host, app_paths)
    try:
        if not dam_setup.is_configured(app_paths):
            configure_logging(app_paths)
            try:
                settings = load_settings(app_paths)
            except Exception as e:
                print_error(f"error: cannot read {dam_setup.settings_path(app_paths)}: {e}")
                raise typer.Exit(EXIT_USER) from None
            chosen = port if port is not None else settings.server_port
            if not built:
                print_error("frontend not built — run `cd frontend && npm ci && npm run build`")
                print_error(dam_setup.NOT_CONFIGURED)
                raise typer.Exit(EXIT_USER)
            lock.publish(chosen)
            typer.echo(f"No archive folder configured yet: setup is on http://127.0.0.1:{chosen}/")
            typer.echo("(or press Ctrl+C and run `dam init` instead)")
            if no_open:
                typer.echo(f"Sign a browser in with: {auth_url(chosen, token)}")
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
                print_error(f"error: {e}")
                raise typer.Exit(EXIT_USER) from None
            print_error("stopped")
            return
        with session(ctx, warn_pending=False) as a:
            if a.activity.pending():  # `dam recover` is refused while this serves
                print_error("warning: interrupted operations found; use Run recovery in the app.")
            port = port if port is not None else a.settings.server_port
            if not built:  # the API still works; a browser would only show a 404
                print_error("frontend not built — run `cd frontend && npm ci && npm run build`")
            lock.publish(port)
            name = f" ({profile.name})" if len(store.load()) > 1 else ""
            typer.echo(f"serving on http://127.0.0.1:{port}/{name} (Ctrl+C to stop)")
            if no_open:
                typer.echo(f"Sign a browser in with: {auth_url(port, token)}")
            api = create_api(a, dam_serve.STATIC_DIR, archives)
            # serve() reads the same token (beside the archive list) for the browser link
            dam_serve.serve(a, api, port, open_browser=built and not no_open, host=host)
            print_error("stopped")
    finally:
        lock.release()


def _serving_port(store: ProfileStore, chosen: Profile) -> int | None:
    """The port of the server that has ``chosen`` open, else of any server that has one
    of the archives open (a switch in the app moves a server to another archive)."""
    profiles = [chosen, *(p for p in store.load() if p.id != chosen.id)]
    for p in profiles:
        holder = ServeLock.holder(p.data_dir)
        if holder and not holder.get("command") and isinstance(holder.get("port"), int):
            return holder["port"]
    return None


@app.command("open")
def open_(
    ctx: typer.Context,
    print_only: Annotated[
        bool, typer.Option("--print", help="Print the sign-in link instead of opening it.")
    ] = False,
) -> None:
    """Open the running app in the browser and sign the browser in.

    Use it for a browser that says it is not signed in, or after `dam serve --no-open`.
    Changes nothing; exit 1 when no `dam serve` is running.
    """
    store = store_of(ctx)
    port = _serving_port(store, ctx.meta["dam.profile"])
    token = read_token(store.base)
    if port is None or token is None:
        print_error("error: dam is not running. Start it with `dam serve`.")
        raise typer.Exit(EXIT_USER)
    url = auth_url(port, token)
    if print_only:
        typer.echo(url)
        return
    if not webbrowser.open(url):
        typer.echo(url)
