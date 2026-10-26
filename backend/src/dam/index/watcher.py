"""Filesystem watcher: debounced subtree scans plus a periodic full reconcile."""

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from dam.core.paths import ArchivePaths, OutsideArchiveError
from dam.index.repo import FileRepo
from dam.index.scanner import ScanReport, is_ignored, scan

log = logging.getLogger(__name__)

_JOIN_TIMEOUT_S = 5.0
_MAX_BACKOFF_S = 300.0
_FOLDER_CHECK_S = 30.0
_NOISE_EVENTS = {"opened", "closed_no_write"}


def _scope(rels: list[str]) -> str:
    """Deepest folder containing every changed path; "" only when they span top-level folders.

    A single changed path (or several under one top-level folder) never widens to the root.
    """
    split = [PurePosixPath(r).parts for r in rels]
    common: list[str] = []
    for parts in zip(*split, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "/".join(common)


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "Watcher") -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in _NOISE_EVENTS:
            return
        for raw in (event.src_path, getattr(event, "dest_path", "")):
            if raw:
                self._watcher._note(os.fsdecode(raw))


class Watcher:
    """Keep the index in sync with the archive folder.

    ``on_change`` is called after every successful scan, from the debounce thread (event
    scans) and from the reconcile thread (full scans), so it may run concurrently with
    itself and must be thread-safe.
    """

    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        on_change: Callable[[], None] | None = None,
        debounce_s: float = 2.0,
        reconcile_every_s: float = 900,
        folder_check_s: float = _FOLDER_CHECK_S,
        max_wait_s: float | None = None,
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.on_change = on_change
        self.debounce_s = debounce_s
        self.reconcile_every_s = reconcile_every_s
        self.folder_check_s = folder_check_s
        self.max_wait_s = max(10 * debounce_s, 30.0) if max_wait_s is None else max_wait_s
        self._pending: set[str] = set()
        self._first_pending: float | None = None  # monotonic time pending went non-empty
        self._backoff = 0.0
        self._lock = threading.Lock()
        # Serialises refresh_watches. Never taken by _note: watchdog calls the handler while
        # holding its own lock, so schedule/unschedule must not run under self._lock.
        self._watch_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._observer = Observer()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._watches: dict[str, ObservedWatch] = {}  # folder label ("" = main) -> watch
        self._primed = False  # the first refresh_watches() is the initial setup

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.refresh_watches()
        self._observer.start()
        for name, target in (
            ("debounce", self._debounce_loop),
            ("reconcile", self._reconcile_loop),
            ("folders", self._folders_loop),
        ):
            t = threading.Thread(target=target, name=f"dam-watcher-{name}", daemon=True)
            t.start()
            self._threads.append(t)

    def refresh_watches(self) -> list[str]:
        """Watch every connected folder and drop the watch of one that went away.

        Returns the labels of extra folders that were not watched before and are now (a disk
        plugged back in); the caller rescans them. The first call only sets up the initial
        watches and returns nothing. The main folder is watched once and never dropped here.
        """
        reconnected: list[str] = []
        with self._watch_lock:
            first, self._primed = not self._primed, True
            for folder in self.paths.folders:
                label = folder.label  # "" for the main folder
                watched = label in self._watches
                if label and not self.paths.is_connected(folder.label):
                    if watched:
                        watch = self._watches.pop(label)
                        try:
                            self._observer.unschedule(watch)
                        except Exception:
                            log.exception("cannot unwatch archive folder '%s'", label)
                        log.warning("archive folder '%s' went away; no longer watched", label)
                    continue
                if watched:
                    continue
                try:
                    self._watches[label] = self._observer.schedule(
                        _Handler(self), str(folder.root), recursive=True
                    )
                except OSError:
                    if not label:
                        raise
                    log.warning("cannot watch archive folder '%s' (%s)", label, folder.root)
                    continue
                if label and not first:
                    reconnected.append(label)
        return reconnected

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._started:
            self._observer.stop()
            self._observer.join(_JOIN_TIMEOUT_S)
        for t in self._threads:
            t.join(_JOIN_TIMEOUT_S)
            if t.is_alive():
                log.warning("watcher thread %s still running after stop()", t.name)
        self._threads.clear()

    # -- event intake -------------------------------------------------------

    def _note(self, abs_path: str) -> None:
        try:
            rel = self.paths.rel(Path(abs_path))
        except (OutsideArchiveError, OSError):
            return
        if not rel:  # the root itself changed (e.g. its mtime); nothing specific to scan
            return
        if any(is_ignored(part) for part in PurePosixPath(rel).parts):
            return
        with self._lock:
            if not self._pending:
                self._first_pending = time.monotonic()
            self._pending.add(rel)
        self._wake.set()

    # -- worker threads -----------------------------------------------------

    def _debounce_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            # Quiet period: keep waiting while new events keep arriving, but never longer
            # than max_wait_s from the first one (a long sync must not starve scans).
            with self._lock:
                first = self._first_pending or time.monotonic()
            while not self._stop.is_set():
                remaining = self.max_wait_s - (time.monotonic() - first)
                if remaining <= 0:
                    break
                self._wake.clear()
                if not self._wake.wait(min(self.debounce_s, remaining)):
                    break
            if self._stop.is_set():
                return
            with self._lock:
                rels, self._pending = sorted(self._pending), set()
                self._first_pending = None
            if not rels:
                continue
            try:
                report = scan(self.paths, self.repo, subtree=_scope(rels))
            except Exception as e:
                self._retry_later(rels, e)
                continue
            self._backoff = 0.0
            if self._aborted(report):
                continue  # the next reconcile catches up once the archive is back
            self._call_on_change()

    def _retry_later(self, rels: list[str], error: Exception) -> None:
        """Requeue a failed batch; the retry delay doubles (up to 300 s) while it keeps failing."""
        first_failure = self._backoff == 0.0
        self._backoff = min(max(self._backoff * 2, self.debounce_s), _MAX_BACKOFF_S)
        if first_failure:
            log.exception("watcher scan failed for %d changed paths; will retry", len(rels))
        else:
            log.warning("watcher scan still failing (%s); retrying in %.1fs", error, self._backoff)
        with self._lock:
            self._pending.update(rels)
            if self._first_pending is None:
                self._first_pending = time.monotonic()
        if not self._stop.wait(self._backoff):
            self._wake.set()

    def _aborted(self, report: ScanReport | None) -> bool:
        if report is None:
            return False
        if report.offline:
            log.warning("archive folders not connected: %s", ", ".join(report.offline))
        if not report.aborted:
            return False
        log.warning("archive folder %s is not available; scan skipped, index kept", self.paths.root)
        return True

    def _call_on_change(self) -> None:
        # A scan can outlive stop() (it is not interrupted): after a reopen the new App's
        # watcher owns the follow-up work, so this one never syncs next to it.
        if self.on_change is None or self._stop.is_set():
            return
        try:
            self.on_change()
        except Exception:
            log.exception("watcher on_change callback failed")

    def _reconcile_loop(self) -> None:
        while not self._stop.wait(self.reconcile_every_s):
            try:
                report = scan(self.paths, self.repo)
            except Exception:
                log.exception("watcher reconcile scan failed")
                continue
            if not self._aborted(report):
                self._call_on_change()

    def _folders_loop(self) -> None:
        while not self._stop.wait(self.folder_check_s):
            try:
                reconnected = self.refresh_watches()
                for label in reconnected:
                    if self._stop.is_set():
                        return
                    # Changes made while the folder was away were never seen as events.
                    report = scan(self.paths, self.repo, subtree=label)
                    if not self._aborted(report):
                        self._call_on_change()
            except Exception:
                log.exception("watcher folder check failed")
