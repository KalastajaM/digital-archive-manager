"""Content indexer: hash and extract text from files awaiting indexing."""

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from dam.core.paths import ArchivePaths
from dam.extract.base import ExtractedText, ExtractorRegistry, UnsupportedContent
from dam.index.barcodes import read_page1
from dam.index.repo import FileRecord, FileRepo

log = logging.getLogger(__name__)

IDLE_WAIT_S = 30.0
MAX_READERS = 3
MAX_BYTES = 256 * 1024 * 1024
MAX_REASON = 500  # characters of an error reason kept in the index


def describe_error(exc: BaseException) -> str:
    """A one-line reason for the index's error list: ``"ValueError: message"``."""
    message = " ".join(str(exc).split())
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return text[:MAX_REASON]


def _read_file(path: Path) -> tuple[str, bytes | None]:
    """Read the whole file once (forcing a Drive download): (sha256, bytes).

    The bytes are None when the file exceeds ``MAX_BYTES``; the hash is then streamed.
    """
    digest = hashlib.sha256()
    buf: bytearray | None = bytearray()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
            if buf is not None:
                buf += chunk
                if len(buf) > MAX_BYTES:
                    buf = None
    return digest.hexdigest(), None if buf is None else bytes(buf)


@dataclass
class _Outcome:
    sha: str | None = None
    extracted: ExtractedText | None = None
    unsupported: bool = False
    reason: str | None = None  # why it is unsupported
    error: BaseException | None = None
    read_done: bool = False
    abandoned: bool = False


class ContentIndexer:
    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        engine: Engine,
        registry: ExtractorRegistry,
        reads_per_minute: int,
        read_timeout_s: float = 60,
        extract_timeout_s: float = 300,
        barcode_timeout_s: float = 120,
        barcode_retry_s: float = 3600,
        barcode_trays: Callable[[], Collection[str]] | None = None,
    ) -> None:
        if reads_per_minute <= 0:
            raise ValueError("reads_per_minute must be positive")
        self.paths = paths
        self.repo = repo
        self.engine = engine
        self.registry = registry
        self.reads_per_minute = reads_per_minute
        self.read_timeout_s = read_timeout_s
        self.extract_timeout_s = extract_timeout_s
        self.barcode_timeout_s = barcode_timeout_s
        # a file whose read timed out is not recorded ("none found" only means a read
        # that finished): it is left for a later pass, not before this many seconds
        self.barcode_retry_s = barcode_retry_s
        self._barcode_retry: dict[str, float] = {}  # drive_id -> monotonic retry time
        # the trays whose open items' files get the barcode pass too (besides the
        # inbox); the App wires the trays with an IBAN field
        self.barcode_trays = barcode_trays
        # the barcode pass runs one read at a time; a hung read pauses it until it
        # returns on its own
        self._barcode_busy = False
        # Up to MAX_READERS daemon worker threads; a hung read cannot be killed, so it
        # keeps its slot (and its drive_id in flight) until it returns on its own.
        self._slots = threading.BoundedSemaphore(MAX_READERS)
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        """Stop accepting work. Abandoned daemon threads never block interpreter exit."""
        self._closed = True

    def run_once(self, limit: int = 20, now: float | None = None) -> int:
        now = time.time() if now is None else now
        if self._closed:
            return 0
        with self._lock:
            busy = len(self._inflight)
        done = 0
        for rec in self.repo.next_for_content(limit + busy, now):
            if done >= limit or self._closed:
                break
            with self._lock:
                if rec.drive_id in self._inflight:
                    continue  # still being read: no new attempt
            expect = (rec.size, rec.mtime)
            done += 1
            try:
                path = self.paths.abs(rec.path)
                if not self._slots.acquire(blocking=False):
                    done -= 1
                    break  # every reader is stuck: pause
                self._process(rec, path, now)
            except Exception as exc:
                log.warning("content indexing failed for %s", rec.path, exc_info=True)
                reason = describe_error(exc)
                try:
                    self.repo.save_content(
                        rec.drive_id, None, None, "error", expect=expect, reason=reason
                    )
                except Exception:
                    log.warning("could not mark %s as error", rec.path, exc_info=True)
        return done

    def _job(self, rec: FileRecord, path: Path, out: _Outcome, events: tuple) -> None:
        read_done, finished = events
        try:
            sha, data = _read_file(path)
            with self._lock:
                out.sha = sha
                skip = out.abandoned  # the read timed out and was already reported
                out.read_done = True
            read_done.set()
            if skip:
                return
            if data is None:
                out.unsupported = True  # over the size cap: hashed, not extracted
                out.reason = f"too large to extract (over {MAX_BYTES // 2**20} MB)"
                return
            try:
                out.extracted = self.registry.extract(path, data)
                if out.extracted is None:
                    out.reason = "no text extractor for this file type"
            except UnsupportedContent as exc:
                log.info("unsupported content in %s: %s", rec.path, exc)
                out.unsupported = True
                out.reason = (str(exc) or "unsupported content")[:MAX_REASON]
        except BaseException as exc:  # noqa: BLE001 - handed to the caller for classification
            out.error = exc
        finally:
            read_done.set()
            with self._lock:
                self._inflight.discard(rec.drive_id)
            self._slots.release()
            finished.set()

    def _process(self, rec: FileRecord, path: Path, now: float) -> None:
        """Start the job in a daemon thread (slot already held); record the outcome."""
        expect = (rec.size, rec.mtime)
        out = _Outcome()
        read_done, finished = threading.Event(), threading.Event()
        with self._lock:
            self._inflight.add(rec.drive_id)
        try:
            threading.Thread(
                target=self._job,
                args=(rec, path, out, (read_done, finished)),
                daemon=True,
                name="dam-read",
            ).start()
        except BaseException:
            with self._lock:
                self._inflight.discard(rec.drive_id)
            self._slots.release()
            raise
        if not read_done.wait(self.read_timeout_s):
            with self._lock:
                late = not out.read_done
                out.abandoned = late
            if late:
                self._cloud_pending(
                    rec, now, TimeoutError(f"read > {self.read_timeout_s}s"), expect
                )
                return
        if not finished.wait(self.extract_timeout_s):
            log.warning("extraction timeout for %s", rec.path)
            reason = f"text extraction took longer than {self.extract_timeout_s:g} s"
            self.repo.save_content(
                rec.drive_id, out.sha, None, "error", expect=expect, reason=reason
            )
        elif isinstance(out.error, OSError):
            self._cloud_pending(rec, now, out.error, expect)
        elif out.error is not None:
            log.warning("extraction failed for %s: %r", rec.path, out.error, exc_info=out.error)
            self.repo.save_content(
                rec.drive_id,
                out.sha,
                None,
                "error",
                expect=expect,
                reason=describe_error(out.error),
            )
        elif out.unsupported or out.extracted is None:
            self.repo.save_content(
                rec.drive_id, out.sha, None, "unsupported", expect=expect, reason=out.reason
            )
        else:
            self.repo.save_content(rec.drive_id, out.sha, out.extracted, "indexed", expect=expect)

    # -- the barcode pass ------------------------------------------------------

    def run_barcodes_once(self, limit: int = 1) -> int:
        """Read bank barcodes and filing-code QR stickers off up to ``limit`` indexed PDFs
        and images (inbox files, then open items' files in ``barcode_trays``) that have no
        reading for their current content; record each finished read, "none found"
        included, so a file is read again only when its sha256 changes. Each read has
        ``barcode_timeout_s``: a read that times out is not recorded, and the file waits
        ``barcode_retry_s`` before a later pass tries it again. Content indexing is
        never involved. Returns the number of files attempted."""
        if self._closed:
            return 0
        with self._lock:
            if self._barcode_busy:
                return 0
        try:
            trays = list(self.barcode_trays()) if self.barcode_trays else []
        except Exception:
            log.warning("could not list the trays for the barcode pass", exc_info=True)
            trays = []
        now = time.monotonic()
        with self._lock:
            self._barcode_retry = {d: t for d, t in self._barcode_retry.items() if t > now}
            waiting = set(self._barcode_retry)
        done = 0
        for rec in self.repo.next_for_barcodes(limit, trays, skip=waiting):
            if self._closed:
                break
            done += 1
            try:
                if not self._read_barcode(rec):
                    break  # the read hangs: pause the pass
            except Exception:
                log.warning("barcode pass failed for %s", rec.path, exc_info=True)
        return done

    def _read_barcode(self, rec: FileRecord) -> bool:
        """Read and record ``rec``'s bank barcode and QR stickers in a daemon thread;
        False if it timed out."""
        assert rec.sha256 is not None and rec.ext is not None
        path = self.paths.abs(rec.path)
        out: dict = {}
        finished = threading.Event()

        def job() -> None:
            try:
                sha, data = _read_file(path)
                if sha == rec.sha256 and data is not None:  # else: changed, or too big
                    found, out["qr"] = read_page1(path, rec.ext, data)
                    out["code"] = found[0] if found else None
            except BaseException as exc:  # noqa: BLE001 - logged by the caller
                out["error"] = exc
            finally:
                with self._lock:
                    self._barcode_busy = False
                finished.set()

        with self._lock:
            self._barcode_busy = True
        try:
            threading.Thread(target=job, daemon=True, name="dam-barcode").start()
        except BaseException:
            with self._lock:
                self._barcode_busy = False
            raise
        if not finished.wait(self.barcode_timeout_s):
            # not "none found": nothing is recorded, so a later pass reads it again
            # (its late result, if it ever returns, is dropped)
            log.warning("barcode reading timed out for %s; retrying later", rec.path)
            with self._lock:
                self._barcode_retry[rec.drive_id] = time.monotonic() + self.barcode_retry_s
            return False
        if "error" in out:
            log.warning("barcode reading failed for %s: %r", rec.path, out["error"])
        # a finished read with anything but a code (none found, an error, changed
        # content) is recorded as "none found" for this content, so the file is not
        # read again until it changes
        self.repo.save_barcode(rec.drive_id, rec.sha256, out.get("code"))
        self.repo.save_qr(rec.drive_id, rec.sha256, out.get("qr", []))
        return True

    def step(self, now: float | None = None) -> int:
        """One unit of background work: a pending file's content, else a barcode read."""
        return self.run_once(limit=1, now=now) or self.run_barcodes_once(limit=1)

    def _cloud_pending(self, rec: FileRecord, now: float, exc: BaseException, expect) -> None:
        attempts = rec.attempts + 1
        retry_at = now + min(3600, 60 * 2**attempts)
        log.info("cannot read %s yet (%r); retry at %s", rec.path, exc, retry_at)
        self.repo.set_index_state(
            rec.drive_id, "cloud_pending", retry_at=retry_at, attempts=attempts, expect=expect
        )

    def run_forever(self, stop: threading.Event, wake: threading.Event | None = None) -> None:
        """Index one file at a time, at most ``reads_per_minute``, until ``stop`` is set.

        When idle it waits up to ``IDLE_WAIT_S``; setting ``wake`` (e.g. after a scan)
        ends the idle wait early. ``wake`` never shortens the rate-limit pause. Whoever
        sets ``stop`` should also set ``wake`` so an idle loop notices at once.
        """
        pause = 60 / self.reads_per_minute
        while not stop.is_set():
            if wake is not None:
                wake.clear()  # before the pass: a wake set during it ends the next wait
            try:
                count = self.step()
            except Exception:
                log.exception("content indexer pass failed")
                count = 0
            if count:
                stop.wait(pause)
            elif wake is None:
                stop.wait(IDLE_WAIT_S)
            else:
                wake.wait(IDLE_WAIT_S)
