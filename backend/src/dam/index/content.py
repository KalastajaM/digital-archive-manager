"""Content indexer: hash and extract text from files awaiting indexing."""

import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from dam.core.paths import ArchivePaths
from dam.extract import ocr
from dam.extract.base import ExtractedText, ExtractorRegistry, UnsupportedContent
from dam.extract.layout import Page1Layout
from dam.extract.picture import (
    PICTURE_DIR,
    PageThumbs,
    have_pictures,
    picture_name,
    picture_path,
    write_picture,
)
from dam.index.barcodes import read_page1
from dam.index.layouts import IMAGE_EXTS, read_layout, render_picture
from dam.index.repo import FileRecord, FileRepo

log = logging.getLogger(__name__)

IDLE_WAIT_S = 30.0
MAX_READERS = 3
MAX_BYTES = 256 * 1024 * 1024
LAYOUT_NO_OCR = "no OCR engine"  # why a file's page 1 cannot be read now
LAYOUT_MISSING = "missing"
LAYOUT_TIMEOUT = "page 1 took too long to read"
PICTURE_PAGE_ROWS = 200  # files whose picture is checked per idle pass (backfill)
LAYOUT_NO_PICTURE = "no picture of page 1 can be made"
BURST_S = 1800.0  # "read now" gives up after this long
BURST_PAUSE_S = 0.05  # the pause between reads while documents are read now
CLOUD_SLOW_S = 3.0  # a page-1 read that took this long counts as slow (a download, a big scan)
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
        page1_backfill: Callable[[], bool] | None = None,
        ocr_languages: list[str] | None = None,
        layout_timeout_s: float = 120,
        layout_retry_s: float = 3600,
        cache_dir: Path | None = None,
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
        # the layout pass (page 1's lines with their boxes, for files indexed before
        # positions were kept): whether it also reads files outside the inbox (the
        # inbox and the wanted files are always read), and the OCR languages of scans
        self.page1_backfill = page1_backfill
        # reads per minute for page 1 of a PDF with a text layer (no OCR); the scans, photos
        # and slow reads keep ``reads_per_minute``. None: the same rate for all.
        self.page1_fast_per_minute: Callable[[], int] | None = None
        self._layout_fast = True  # whether the last page-1 read was a quick, local one
        self._last_slow = True  # whether the step before was a slow kind of work
        self.ocr_languages = ocr_languages or ["en-US"]
        self.layout_timeout_s = layout_timeout_s
        self.layout_retry_s = layout_retry_s
        self._layout_retry: dict[str, float] = {}  # drive_id -> monotonic retry time
        self._layout_done: deque[float] = deque(maxlen=2000)  # when reads finished (monotonic)
        self._layout_why: dict[str, str] = {}  # drive_id -> why it waits (no OCR engine)
        # the page-1 pictures (picture areas) are kept in this cache folder; None: not kept
        self.cache_dir = cache_dir
        # tiny thumbnails of the pictures (a rough ranking for a rule test): set by the App
        self.thumbs: PageThumbs | None = None
        # files whose picture cannot be made (until the content changes or dam restarts)
        self._no_picture: dict[str, str] = {}  # drive_id -> sha256
        self._picture_cursor = 0  # where the next backfill page of picture checks starts
        self._wanted: set[str] = set()  # asked for by a replay, read next
        # asked for by the user to be read now: read at full speed (one at a time, with
        # the usual time limit) until none is left, or for at most ``BURST_S``
        self._burst: set[str] = set()
        self._burst_until = 0.0
        self._layout_busy = False
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
        if self.thumbs is not None:
            self.thumbs.flush(force=True)

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
            saved = self.repo.save_content(
                rec.drive_id, out.sha, out.extracted, "indexed", expect=expect
            )
            if saved and out.extracted.page1 is not None:
                # the page was rendered for OCR anyway: keep its picture
                self._keep_picture(rec.drive_id, out.sha, out.extracted.page1.picture)

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
        # a file queued only for its QR stickers (read before 0026) also rewrites its
        # bank barcode row: same content, so the same result
        self.repo.save_barcode(rec.drive_id, rec.sha256, out.get("code"))
        self.repo.save_qr(rec.drive_id, rec.sha256, out.get("qr", []))
        return True

    # -- the layout pass -------------------------------------------------------

    def want_layouts(self, drive_ids: Collection[str]) -> None:
        """Ask for page 1 of these files to be read next (after the inbox); forgotten
        once read. Cheap and safe to call from any thread."""
        with self._lock:
            self._wanted.update(drive_ids)

    def read_now(self, drive_ids: Collection[str]) -> int:
        """Read page 1 of these files next, one at a time and without the pause between
        reads (each read still has its time limit), until they are all read or cannot be
        read now. Returns how many were queued. Cheap and safe to call from any thread."""
        ids = set(drive_ids)
        with self._lock:
            self._wanted.update(ids)
            self._burst.update(ids)
            self._burst_until = time.monotonic() + BURST_S
        return len(ids)

    def reading_now(self) -> int:
        """How many files asked for with ``read_now`` are still waiting to be read."""
        with self._lock:
            return len(self._burst_pending())

    def _burst_pending(self) -> set[str]:
        """The ``read_now`` files not read yet and not put off (call with the lock held)."""
        if time.monotonic() > self._burst_until:
            self._burst.clear()
        self._burst &= self._wanted
        self._burst -= set(self._layout_retry) | set(self._no_picture)
        return self._burst

    def layout_blocked(self, drive_id: str) -> str | None:
        """Why page 1 of this file cannot be read right now (``LAYOUT_NO_OCR``,
        ``LAYOUT_MISSING`` or ``LAYOUT_TIMEOUT``), else None."""
        with self._lock:
            failed = self._no_picture.get(drive_id)
            why = self._layout_why.get(drive_id)
        if failed is not None and why is None:
            # the failure is of one content: a file that has changed since is not blocked
            rec = self.repo.get(drive_id)
            if rec is not None and rec.sha256 == failed:
                return LAYOUT_NO_PICTURE
        return why

    def layout_rate(self, window_s: float = 600.0) -> float | None:
        """Page-1 reads finished per minute over the last ``window_s`` seconds (None: too few
        to say, such as right after start or when nothing is being read)."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._layout_done if now - t <= window_s]
        if len(recent) < 3:
            return None
        return round(len(recent) / max(now - recent[0], 30.0) * 60, 1)

    def layout_waiting(self) -> list[tuple[str, int]]:
        """``(reason, how many)`` for the documents whose page 1 cannot be read right now,
        most first: those waiting to be tried again (with the reason when it is known, such
        as no OCR engine) and those whose page-1 picture cannot be made."""
        counts: dict[str, int] = {}
        with self._lock:
            for drive_id in self._layout_retry:
                why = self._layout_why.get(drive_id) or "will be tried again"
                counts[why] = counts.get(why, 0) + 1
            if self._no_picture:
                counts[LAYOUT_NO_PICTURE] = counts.get(LAYOUT_NO_PICTURE, 0) + len(self._no_picture)
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def _keep_picture(self, drive_id: str, sha256: str | None, picture) -> bool:
        """Keep ``picture`` as the page-1 picture of this content in the cache; never
        fails the caller."""
        if self.cache_dir is None or picture is None or not sha256:
            return False
        try:
            write_picture(self.cache_dir, drive_id, sha256, picture)
        except Exception:
            log.warning("could not keep the page-1 picture of %s", drive_id, exc_info=True)
            return False
        if self.thumbs is not None:
            try:
                self.thumbs.add(picture_name(drive_id, sha256), picture)
            except Exception:
                log.warning("could not make the thumbnail of %s", drive_id, exc_info=True)
        return True

    def run_thumbs_once(self, limit: int = 300) -> int:
        """Make the thumbnails of up to ``limit`` page-1 pictures in the cache that have
        none (pictures made before thumbnails were kept), drop those of pictures that are
        gone, and write the file when it changed. It reads only the cache, never the
        archive. Returns how many thumbnails were made."""
        if self._closed or self.thumbs is None or self.cache_dir is None:
            return 0
        have = have_pictures(self.cache_dir)
        self.thumbs.forget_missing(have)
        folder = Path(self.cache_dir) / PICTURE_DIR
        todo = {n: folder / n for n in sorted(have) if not self.thumbs.has(n)}
        wanted = dict(list(todo.items())[:limit])
        if wanted:
            self.thumbs.ensure(wanted, budget_s=5.0)
        self.thumbs.flush()
        return len(wanted)

    def _next_for_pictures(
        self, limit: int, wanted: set[str], waiting: set[str], backfill: bool
    ) -> list[FileRecord]:
        """Files whose layout is read but whose page-1 picture is not in the cache. The
        inbox and the wanted files are looked at every time; the rest (backfill) a page of
        ``PICTURE_PAGE_ROWS`` rows per pass, round and round, so an archive with nothing to
        do costs a few file checks per pass, not a listing of the whole cache."""
        if self.cache_dir is None or limit <= 0:
            return []
        with self._lock:
            failed = dict(self._no_picture)

        def missing(rows: list[tuple[str, str]]) -> tuple[list[FileRecord], int]:
            out: list[FileRecord] = []
            for i, (drive_id, sha) in enumerate(rows):
                if (
                    failed.get(drive_id) == sha
                    or picture_path(self.cache_dir, drive_id, sha).is_file()
                ):
                    continue
                rec = self.repo.get(drive_id)
                if rec is not None:
                    out.append(rec)
                if len(out) >= limit:
                    return out, i + 1
            return out, len(rows)

        found, _ = missing(self.repo.next_for_pictures(wanted, waiting, everything=False))
        if found or not backfill:
            return found
        start = self._picture_cursor
        page = self.repo.next_for_pictures(
            wanted, waiting, everything=True, limit=PICTURE_PAGE_ROWS, offset=start
        )
        found, used = missing(page)
        # the next pass goes on after the rows looked at; at the end of the list, from the top
        self._picture_cursor = (
            0 if len(page) < PICTURE_PAGE_ROWS and used == len(page) else start + used
        )
        return found

    def run_layouts_once(self, limit: int = 1, backfill: bool | None = None) -> int:
        """Read page 1 of up to ``limit`` indexed PDFs and images that have no layout
        for their current content: inbox files, then the wanted ones, then (while
        ``page1_backfill`` is on, or ``backfill`` says so) the rest by path. Each finished
        read is recorded, an empty page included, so a file is read again only when its
        sha256 changes. A read has ``layout_timeout_s``; one that times out, or needs an
        OCR engine that is not installed, is not recorded and waits ``layout_retry_s``.
        The same pass keeps each file's page-1 picture in the cache (``cache_dir``): the
        read of a layout that renders the page gives it along, and a file whose layout is
        read already but whose picture is not in the cache gets only the picture (after the
        layouts, with the same order and the same ``backfill`` rule).
        Returns the number of files attempted."""
        if self._closed:
            return 0
        with self._lock:
            if self._layout_busy:
                return 0
        self._layout_fast = True
        now = time.monotonic()
        with self._lock:
            self._layout_retry = {d: t for d, t in self._layout_retry.items() if t > now}
            self._layout_why = {
                d: w for d, w in self._layout_why.items() if d in self._layout_retry
            }
            waiting = set(self._layout_retry)
            wanted = set(self._wanted)
        if backfill is None:
            try:
                backfill = True if self.page1_backfill is None else bool(self.page1_backfill())
            except Exception:
                log.warning("could not read the page-1 setting", exc_info=True)
                backfill = True
        done = 0
        for rec in self.repo.next_for_layouts(limit, wanted, skip=waiting, everything=backfill):
            if self._closed:
                break
            done += 1
            try:
                if not self._read_layout(rec):
                    break  # the read hangs: pause the pass
            except Exception:
                log.warning("layout pass failed for %s", rec.path, exc_info=True)
        else:
            for rec in self._next_for_pictures(limit - done, wanted, waiting, backfill):
                if self._closed:
                    break
                done += 1
                try:
                    if not self._read_layout(rec, layout=False):
                        break
                except Exception:
                    log.warning("picture pass failed for %s", rec.path, exc_info=True)
        return done

    def _read_layout(self, rec: FileRecord, layout: bool = True) -> bool:
        """Read and record ``rec``'s page-1 layout, and keep its page-1 picture, in a
        daemon thread; False if it timed out. ``layout`` false: the layout is there, only
        the picture is made (no OCR needed)."""
        assert rec.sha256 is not None and rec.ext is not None
        path = self.paths.abs(rec.path)
        ocr_used = self.repo.text_was_ocrd(rec.drive_id)
        ext = rec.ext.lower().lstrip(".")
        if layout and (ext in IMAGE_EXTS or (ext == "pdf" and ocr_used)) and ocr.engine() is None:
            # this read needs OCR: do not read the whole file just to find that out
            self._retry_layout_later(rec.drive_id, LAYOUT_NO_OCR)
            return True
        needs_ocr = layout and (ext in IMAGE_EXTS or (ext == "pdf" and bool(ocr_used)))
        started = time.monotonic()
        out: dict = {}
        finished = threading.Event()

        def job() -> None:
            try:
                sha, data = _read_file(path)
                if sha == rec.sha256 and data is not None:  # else: changed, or too big
                    if layout:
                        out["layout"] = read_layout(
                            path,
                            rec.ext,
                            data,
                            ocr_used=bool(ocr_used),
                            languages=self.ocr_languages,
                        )
                    else:
                        out["picture"] = render_picture(path, rec.ext, data)
                else:
                    out["gone"] = True
            except BaseException as exc:  # noqa: BLE001 - classified by the caller
                out["error"] = exc
            finally:
                with self._lock:
                    self._layout_busy = False
                finished.set()

        with self._lock:
            self._layout_busy = True
        try:
            threading.Thread(target=job, daemon=True, name="dam-layout").start()
        except BaseException:
            with self._lock:
                self._layout_busy = False
            raise
        if not finished.wait(self.layout_timeout_s):
            log.warning("page-1 reading timed out for %s; retrying later", rec.path)
            self._retry_layout_later(rec.drive_id, LAYOUT_TIMEOUT)
            self._layout_fast = False
            return False
        error = out.get("error")
        # a scan (OCR) and a read that took long (a cloud file that had to be downloaded, a
        # big file) keep the indexer's slow pace; a quick local text-layer read does not
        if needs_ocr or isinstance(error, OSError) or time.monotonic() - started > CLOUD_SLOW_S:
            self._layout_fast = False
        if not layout:
            return self._finish_picture(rec, out)
        if isinstance(error, UnsupportedContent) and str(error) == ocr.NO_OCR:
            self._retry_layout_later(rec.drive_id, LAYOUT_NO_OCR)  # not "read": try later
            return True
        if isinstance(error, OSError):  # gone, or a cloud file that cannot be fetched now
            self._retry_layout_later(rec.drive_id, LAYOUT_MISSING)
            return True
        if error is not None:
            log.warning("page-1 reading failed for %s: %r", rec.path, error)
        # a finished read with anything but lines (an error, changed or oversize
        # content) is recorded as "no text" for this content, so it is not read again
        # until the content changes
        read = out.get("layout") or Page1Layout([], "text-layer")
        if self.repo.save_layout(rec.drive_id, rec.sha256, read):
            self._keep_picture(rec.drive_id, rec.sha256, read.picture)
        with self._lock:
            self._wanted.discard(rec.drive_id)
            self._layout_done.append(time.monotonic())
        return True

    def _finish_picture(self, rec: FileRecord, out: dict) -> bool:
        """The outcome of a picture-only read: kept in the cache, or the reason it cannot
        be made (now: tried again later; for good: until the content changes)."""
        assert rec.sha256 is not None
        error = out.get("error")
        if isinstance(error, OSError):  # gone, or a cloud file that cannot be fetched now
            self._retry_layout_later(rec.drive_id, LAYOUT_MISSING)
            return True
        picture = out.get("picture")
        if picture is not None and self._keep_picture(rec.drive_id, rec.sha256, picture):
            with self._lock:
                self._no_picture.pop(rec.drive_id, None)
                self._wanted.discard(rec.drive_id)
                self._layout_done.append(time.monotonic())
            return True
        if error is not None:
            log.warning("page-1 picture failed for %s: %r", rec.path, error)
        # changed or oversize content, a page that cannot be rendered, a cache that cannot
        # be written: not tried again until the content changes (or dam restarts)
        with self._lock:
            self._no_picture[rec.drive_id] = rec.sha256
            self._wanted.discard(rec.drive_id)
        return True

    def _retry_layout_later(self, drive_id: str, why: str | None) -> None:
        with self._lock:
            self._layout_retry[drive_id] = time.monotonic() + self.layout_retry_s
            if why is not None:
                self._layout_why[drive_id] = why

    def step(self, now: float | None = None) -> int:
        """One unit of background work: a pending file's content, else a barcode read,
        else a page-1 layout read, else the thumbnails of page-1 pictures."""
        done = self.run_once(limit=1, now=now) or self.run_barcodes_once(limit=1)
        if done:
            self._last_slow = True
            return done
        done = self.run_layouts_once(limit=1)
        if done:
            self._last_slow = not self._layout_fast
            return done
        self._last_slow = False
        return self.run_thumbs_once()

    def pause_s(self) -> float:
        """How long to wait after the last step: the indexer's pace (``reads_per_minute``)
        after content, barcode and slow page-1 reads (a scan, a slow download), the faster
        page-1 pace after a quick text-layer read. Never slower than the indexer's pace."""
        slow = 60 / self.reads_per_minute
        with self._lock:
            if self._burst_pending():
                return min(slow, BURST_PAUSE_S)
        if self._last_slow or self.page1_fast_per_minute is None:
            return slow
        try:
            fast = 60 / max(1, int(self.page1_fast_per_minute()))
        except Exception:
            return slow
        return min(fast, slow)

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
        while not stop.is_set():
            if wake is not None:
                wake.clear()  # before the pass: a wake set during it ends the next wait
            try:
                count = self.step()
            except Exception:
                log.exception("content indexer pass failed")
                count = 0
            if count:
                stop.wait(self.pause_s())
            elif wake is None:
                stop.wait(IDLE_WAIT_S)
            else:
                wake.wait(IDLE_WAIT_S)
