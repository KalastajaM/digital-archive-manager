"""``dam serve``: run uvicorn on 127.0.0.1 with the background work around it.

Background work (initial scan, watcher, content indexer, hourly reminder check) starts
only once the server is listening, so a failed bind starts nothing. After every
successful scan (the initial one, and each watcher scan) the Ongoing links are synced in
that same background thread, never in a request thread. Reminders are checked a minute
after the start, then every hour. SIGINT and SIGTERM end the server
gracefully and are not re-raised, so the shutdown always runs: stop the background,
then the caller closes the App.

One server shows one archive (profile) at a time. ``Host`` holds what is open and can
swap it for another archive in the same process (``Host.switch``): the other archive's
files are opened first, then the first archive's scanner, watcher, indexer and reminders
are stopped, and only then the other's start, so two archives' background work never runs
at the same time and never on one database. A per-archive lock file (``ServeLock``)
keeps a second process from serving the same archive.
"""

import dataclasses
import logging
import signal
import threading
import time
import webbrowser
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from dam import setup
from dam.app import App
from dam.config import AppPaths
from dam.index.watcher import Watcher
from dam.profiles import Profile, ProfileStore, ServeLock
from dam.reminders.notify import RemindResult, run_reminders
from dam.services.archives import ArchiveService
from dam.services.errors import Conflict

ASGIApp = Callable[[dict, Callable, Callable], object]

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parents[3] / "frontend" / "dist"  # the built frontend
JOIN_TIMEOUT_S = 5.0
GRACEFUL_SHUTDOWN_S = 10  # a hung request cannot hold up shutdown longer than this
_STARTED_POLL_S = 0.05
REMIND_FIRST_S = 60  # the first reminder check, after the start
REMIND_EVERY_S = 3600  # then hourly


@dataclass(eq=False)
class Background:
    app: App
    watcher: Watcher
    stop_event: threading.Event
    wake: threading.Event
    scan_thread: threading.Thread
    indexer_thread: threading.Thread
    reminders_thread: threading.Thread
    _stopped: bool = field(default=False, init=False)

    @property
    def threads(self) -> list[threading.Thread]:
        return [self.scan_thread, self.indexer_thread, self.reminders_thread]

    def stop(self) -> None:
        """Stop the indexer and the watcher and wait (briefly) for the threads.

        The caller still closes the App. A scan cannot be interrupted: one still running
        after the timeout is left behind (it is a daemon thread) and logged.
        """
        if self._stopped:
            return
        self._stopped = True
        _shutdown(self.app, self.watcher, self.stop_event, self.wake, self.threads)


def _shutdown(
    app: App,
    watcher: Watcher,
    stop: threading.Event,
    wake: threading.Event,
    threads: list[threading.Thread],
) -> None:
    stop.set()
    wake.set()
    watcher.stop()
    app.content.close()
    for t in threads:
        if t.ident is None:
            continue  # never started
        t.join(JOIN_TIMEOUT_S)
        if t.is_alive():
            log.warning("background thread %s still running after stop()", t.name)


def _sync_ongoing(app: App) -> None:
    """Repair the Ongoing links (every publisher) after a scan; errors are logged,
    never raised."""
    try:
        app.sync_publishers()  # problems are logged by each sync itself
    except Exception:
        log.exception("ongoing sync failed (the next scan will retry)")


def _initial_scan(app: App, wake: threading.Event) -> None:
    synced = False
    try:
        report = app.scan()
        if report.aborted:
            log.warning(
                "archive folder %s is not available; initial scan skipped, index kept",
                app.paths.root,
            )
        else:
            log.info("initial scan done: %s", report)
            wake.set()  # the indexer need not wait for the sync
            _sync_ongoing(app)
            synced = True
    except Exception:
        log.exception("initial scan failed (the watcher's reconcile will retry)")
    finally:
        if not synced:
            wake.set()  # let the indexer pick up what the scan found


def _after_watcher_scan(app: App, wake: threading.Event) -> None:
    wake.set()
    _sync_ongoing(app)


def _remind_once(app: App) -> None:
    """One reminder check; errors are logged, never raised (a run that raised is noted
    on ``app.last_reminders.errors["run"]``). A check skipped because
    another run (the launchd helper) holds the lock keeps the last completed result
    and only notes the skip on it."""
    try:
        result = run_reminders(app, now=datetime.now().astimezone())
        if result.skipped:
            last = app.last_reminders or RemindResult()
            app.last_reminders = dataclasses.replace(last, skipped=result.skipped)
    except Exception as e:
        log.exception("reminder check failed (the next one is in an hour)")
        # shown on Today (errors["run"]) until a run completes and replaces the result
        last = app.last_reminders or RemindResult()
        errors = {**last.errors, "run": str(e) or type(e).__name__}
        app.last_reminders = dataclasses.replace(last, errors=errors)


def _reminders_loop(app: App, stop: threading.Event) -> None:
    if stop.wait(REMIND_FIRST_S):
        return
    while True:
        _remind_once(app)
        if stop.wait(REMIND_EVERY_S):
            return


def start_background(app: App) -> Background:
    """Start the initial scan (it can take tens of seconds), the watcher, the indexer
    and the hourly reminder check.

    Every scan (initial, watcher) wakes the idle indexer. If starting fails part-way,
    whatever already started is stopped before the error is re-raised.
    """
    stop, wake = threading.Event(), threading.Event()
    app.wake_indexer = wake.set  # e.g. after files are queued for indexing again
    scan_thread = threading.Thread(
        target=_initial_scan, args=(app, wake), name="dam-initial-scan", daemon=True
    )
    indexer_thread = threading.Thread(
        target=app.content.run_forever, args=(stop, wake), name="dam-indexer", daemon=True
    )
    reminders_thread = threading.Thread(
        target=_reminders_loop, args=(app, stop), name="dam-reminders", daemon=True
    )
    watcher = Watcher(app.paths, app.repo, on_change=lambda: _after_watcher_scan(app, wake))
    threads = [scan_thread, indexer_thread, reminders_thread]
    try:
        scan_thread.start()
        watcher.start()
        indexer_thread.start()
        reminders_thread.start()
    except BaseException:
        _shutdown(app, watcher, stop, wake, threads)
        raise
    return Background(app, watcher, stop, wake, scan_thread, indexer_thread, reminders_thread)


class DamServer(uvicorn.Server):
    """uvicorn's server, but a captured SIGINT/SIGTERM is not re-raised after shutdown.

    uvicorn 0.54 re-raises the signal once the server has stopped, which kills the
    process (SIGTERM) or raises KeyboardInterrupt (SIGINT) before any cleanup runs.
    """

    @contextmanager
    def capture_signals(self) -> Generator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        sigs = (signal.SIGINT, signal.SIGTERM)
        originals = {sig: signal.signal(sig, self.handle_exit) for sig in sigs}
        try:
            yield
        finally:
            for sig, handler in originals.items():
                signal.signal(sig, handler)


class Switchboard:
    """An ASGI app that forwards to a current target, which can be swapped while the
    server runs (setup mode -> the normal app, one archive -> another). The lifespan
    always goes to the app the server started with."""

    def __init__(self, first: ASGIApp) -> None:
        self.first = first
        self.target = first

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        await (self.first if scope["type"] == "lifespan" else self.target)(scope, receive, send)


@dataclass(eq=False)
class Opened:
    """One archive as the server has it open: its API, and (once configured) its App and
    background work."""

    profile_id: str | None
    api: ASGIApp
    app: App | None  # None while the archive is in setup mode
    owns_app: bool
    archives: ArchiveService | None = None
    background: Background | None = None
    lock: ServeLock | None = None
    paths: AppPaths | None = None


class Host:
    """What ``dam serve`` serves: one archive at a time, swappable in place."""

    def __init__(
        self,
        store: ProfileStore | None = None,
        static_dir: Path | None = None,
        port: int | None = None,
    ) -> None:
        self.store = store
        self.static_dir = static_dir
        self.port = port
        self.profile_id: str | None = None  # the archive the server starts with ...
        self.first_lock: ServeLock | None = None  # ... and its lock
        self.lock = threading.RLock()
        self.board: Switchboard | None = None
        self.current: Opened | None = None
        self.running = False  # the server is listening: background work may run
        self.stopping = False

    # -- opening ------------------------------------------------------------------------

    def attach(self, board: Switchboard, current: Opened) -> None:
        current.profile_id = self.profile_id
        current.lock = self.first_lock
        self.board, self.current = board, current

    def setup_api(
        self, paths: AppPaths, archives: ArchiveService | None, opened: Opened
    ) -> ASGIApp:
        from dam.api.setup_mode import create_setup_api

        return create_setup_api(
            paths,
            self.static_dir,
            on_configured=lambda: self.activate(opened),
            on_layout=self.make_layout,
            archives=archives,
        )

    def _open(self, profile: Profile, lock: ServeLock) -> Opened:
        """Open ``profile``'s App (or setup mode when it has no archive folder yet).
        Starts nothing in the background; raises with nothing left open."""
        from dam.api import create_api

        paths = profile.paths
        paths.ensure()
        archives = ArchiveService(self.store, profile.id, self, paths)
        opened = Opened(profile.id, None, None, True, archives, lock=lock, paths=paths)  # type: ignore[arg-type]
        if setup.is_configured(paths):
            app = App.create(paths.data_dir)
            try:
                opened.api = create_api(app, self.static_dir, archives)
            except BaseException:
                app.close()
                raise
            opened.app = app
        else:
            opened.api = self.setup_api(paths, archives, opened)
        return opened

    def activate(self, opened: Opened) -> bool:
        """Setup mode -> the normal app for ``opened`` (its folder was just saved)."""
        from dam.api import create_api

        with self.lock:
            if self.stopping or self.current is not opened or opened.paths is None:
                return False
            app = App.create(opened.paths.data_dir)
            try:
                api = create_api(app, self.static_dir, opened.archives)
                background = start_background(app) if self.running else None
            except BaseException:
                app.close()
                raise
            opened.app, opened.api, opened.background = app, api, background
            opened.owns_app = True
            self.board.target = api
            return True

    def make_layout(self, spec):
        with self.lock:
            app = self.current.app if self.current else None
        if app is None:
            raise Conflict("The archive is not open yet.")
        return app.layout.apply(spec, origin="ui")

    # -- background work ----------------------------------------------------------------

    def start_background(self) -> None:
        """The server is listening: start the open archive's background work."""
        with self.lock:
            self.running = True
            cur = self.current
            if cur is not None and cur.app is not None and cur.background is None:
                cur.background = start_background(cur.app)

    # -- switching ----------------------------------------------------------------------

    def switch(self, key: str) -> Profile:
        """Open another archive in this server. The other archive is opened first (a
        failure leaves everything as it was), then this one's background work is
        stopped, then the other's started. ``Locked`` when another process serves it."""
        if self.store is None or self.board is None or self.current is None:
            raise Conflict("This server cannot switch archives; start it with --archive.")
        with self.lock:
            if self.stopping:
                raise Conflict("The server is stopping.")
            target = self.store.find(key)
            if target.id == self.current.profile_id:
                return target
            problem = self.store.root_problems().get(target.id)
            if problem:
                raise Conflict(f"'{target.name}' cannot be opened: {problem}")
            lock = ServeLock(target.data_dir)
            lock.acquire(self.port)  # Locked: another process has it
            try:
                new = self._open(target, lock)
            except BaseException:
                lock.release()
                raise
            old = self.current
            old_api = self.board.target
            self.board.target = new.api  # new requests now go to the other archive
            self.current = new
            old_background = old.background
            try:
                if old_background is not None:
                    old_background.stop()
                    old.background = None
                if self.running and new.app is not None:
                    new.background = start_background(new.app)
                self.store.set_active(target.id)
            except BaseException:
                self._rollback(old, old_api, old_background, new)
                raise
            if old.app is not None:
                old.app.close()
            if old.lock is not None:
                old.lock.release()
            return dataclasses.replace(target, active=True)

    def _rollback(
        self, old: Opened, old_api: ASGIApp, old_background: Background | None, new: Opened
    ) -> None:
        """The switch failed after the first archive was stopped: put it back."""
        log.exception("could not switch archives; staying on the first one")
        if new.background is not None:
            new.background.stop()
            new.background = None
        self.board.target = old_api
        self.current = old
        if old_background is not None and old.app is not None and self.running:
            try:
                old.background = start_background(old.app)
            except Exception:
                log.exception("could not restart the background work after a failed switch")
        if new.app is not None:
            new.app.close()
        if new.lock is not None:
            new.lock.release()

    # -- the end ------------------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop the background work, close what the host opened, release the lock."""
        with self.lock:
            self.stopping = True
            cur = self.current
        if cur is None:
            return
        if cur.background is not None:
            cur.background.stop()
        if cur.owns_app and cur.app is not None:
            cur.app.close()
        if cur.lock is not None:
            cur.lock.release()


def serve(app: App, api: FastAPI, port: int, open_browser: bool, host: Host | None = None) -> None:
    """Run the server until it stops; background work runs only while it is listening.

    Returns normally after SIGINT/SIGTERM. The background is stopped on every way out
    (including an exception from the server); closing the App is the caller's job (an
    archive opened later by a switch is closed here). Our signal handlers are removed
    once the server has stopped, so a second signal during ``background.stop()``
    force-quits: SIGINT raises KeyboardInterrupt (the App is still closed on the way
    out), SIGTERM kills the process at once.
    """
    url = f"http://127.0.0.1:{port}/"
    host = host or Host(port=port)
    host.port = port
    board = Switchboard(api)
    host.attach(board, Opened(None, api, app, owns_app=False))
    server = DamServer(
        uvicorn.Config(
            board, host="127.0.0.1", port=port, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S
        )
    )
    lock = threading.Lock()
    finished = threading.Event()
    failures: list[BaseException] = []

    def after_start() -> None:
        while not server.started:
            if finished.wait(_STARTED_POLL_S):
                return
        with lock:
            if finished.is_set():
                return
            try:
                host.start_background()
            except Exception as e:
                failures.append(e)
                server.should_exit = True  # do not serve without the background work
                return
        if open_browser:
            webbrowser.open(url)

    starter = threading.Thread(target=after_start, name="dam-after-start", daemon=True)
    starter.start()
    try:
        server.run()
    finally:
        with lock:
            finished.set()
        starter.join(JOIN_TIMEOUT_S)
        host.shutdown()
    if failures:
        raise failures[0]


def serve_setup(
    app_paths: AppPaths,
    static_dir: Path,
    port: int,
    open_browser: bool,
    host: Host | None = None,
    archives: ArchiveService | None = None,
) -> None:
    """Run the setup-mode server (no archive folder yet). When the user chooses a
    folder, the same server switches to the normal app and starts the background work,
    no restart needed. Returns after SIGINT/SIGTERM; closes whatever it opened."""
    host = host or Host(static_dir=static_dir, port=port)
    host.static_dir, host.port = static_dir, port
    first = Opened(None, None, None, True, archives, paths=app_paths)  # type: ignore[arg-type]
    first.api = host.setup_api(app_paths, archives, first)
    board = Switchboard(first.api)
    host.attach(board, first)
    server = DamServer(
        uvicorn.Config(
            board, host="127.0.0.1", port=port, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S
        )
    )

    def when_started() -> None:
        while not server.started:
            if host.stopping or server.should_exit:
                return
            time.sleep(_STARTED_POLL_S)
        host.start_background()
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")

    starter = threading.Thread(target=when_started, name="dam-after-start", daemon=True)
    starter.start()
    try:
        server.run()
    finally:
        host.shutdown()
        starter.join(JOIN_TIMEOUT_S)
