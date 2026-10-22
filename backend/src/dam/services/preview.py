"""Previews for any file type: Quick Look thumbnails (macOS ``qlmanage``) and the start
of a text-like file.

Thumbnails are rendered with ``qlmanage -t -s <px> -o <dir> <file>`` (a list of
arguments, a 20 s timeout, at most two at once) into the data dir's cache, one folder
per (content, width): ``<cache>/<sha256, or drive id + mtime + size>_<width>/``.
qlmanage writes ``<file name>.png`` there, and that file is the cache entry: nothing
is renamed or deleted, and nothing is ever written into the archive. A hang, a crash
or no output is "no preview" (404), remembered for a while so a file Quick Look cannot
render does not cost 20 s on every request.
"""

import codecs
import logging
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from dam.core.paths import ArchivePaths, OutsideArchiveError
from dam.index.repo import FileRecord
from dam.services.errors import NotFound
from dam.services.launch import resolve_inside

log = logging.getLogger(__name__)

QLMANAGE = "/usr/bin/qlmanage"
THUMB_TIMEOUT_S = 20
THUMB_MIN_WIDTH, THUMB_MAX_WIDTH, THUMB_DEFAULT_WIDTH = 300, 2000, 1200
# a requested width is rendered at the nearest step at or above it: a bounded cache
THUMB_STEPS = (600, 1200, 2000)
THUMB_WAIT_S = 25  # longest wait for a render slot before answering "no preview"
FAILED_TTL_S = 600  # how long a failed render is not retried
NO_PREVIEW = "no preview"
# Each render is a qlmanage process: at most two at once (cache hits never wait).
THUMB_SEMAPHORE = threading.BoundedSemaphore(2)

TEXT_EXTS = frozenset({"txt", "md", "csv", "log", "json", "xml", "yaml", "yml"})
TEXT_MAX_BYTES = 200 * 1024

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_PNG_END = b"IEND\xaeB`\x82"

# (args, timeout) -> None; raises subprocess.TimeoutExpired when the timeout passes
Runner = Callable[[list[str], float], None]


def run_qlmanage(args: list[str], timeout: float) -> None:
    """Run ``args`` without a shell; ``subprocess.run`` kills it after ``timeout``."""
    subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def thumb_step(width: int) -> int:
    """The smallest step >= ``width`` (the largest for anything above it)."""
    return next((s for s in THUMB_STEPS if s >= width), THUMB_STEPS[-1])


def thumb_key(rec: FileRecord) -> str:
    """The content hash when known (the scanner clears it when the file changes), else
    the drive id with the mtime and size."""
    if rec.sha256:
        return rec.sha256
    stamp = f"{rec.mtime or 0:.6f}".replace(".", "-")
    return f"{_UNSAFE.sub('_', rec.drive_id)}_{stamp}_{rec.size or 0}"


def _complete_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG") and data.endswith(_PNG_END)


def _cached_png(folder: Path) -> bytes | None:
    try:
        candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".png")
    except OSError:
        return None
    for png in candidates:
        try:
            data = png.read_bytes()
        except OSError:
            continue
        if _complete_png(data):
            return data
    return None


class PreviewService:
    def __init__(
        self,
        paths: ArchivePaths,
        cache_dir: Path,
        runner: Runner = run_qlmanage,
        platform: str = sys.platform,
        timeout_s: float = THUMB_TIMEOUT_S,
        wait_s: float = THUMB_WAIT_S,
    ) -> None:
        self.paths = paths
        self.cache_dir = cache_dir
        self.runner = runner
        self.platform = platform
        self.timeout_s = timeout_s
        self.wait_s = wait_s
        self._failed: dict[str, float] = {}  # cache folder name -> monotonic retry time
        self._lock = threading.Lock()

    def _file(self, rec: FileRecord, missing: str) -> Path:
        """``rec``'s regular file, resolved inside the archive; ``NotFound(missing)``
        for a folder, a link, a vanished file or one that resolves outside."""
        path = self.paths.abs(rec.path)
        if rec.is_dir or rec.is_link or path.is_symlink():
            raise NotFound(missing)
        try:
            real = resolve_inside(self.paths, rec)
        except OutsideArchiveError:
            log.warning("preview refused: %s resolves outside the archive", rec.path)
            raise NotFound(missing) from None
        except NotFound:
            raise NotFound(missing) from None
        if not real.is_file():
            raise NotFound(missing)
        return real

    # -- thumbnails ---------------------------------------------------------------

    def thumbnail(self, rec: FileRecord, width: int = THUMB_DEFAULT_WIDTH) -> bytes:
        """A PNG of ``rec`` from Quick Look, rendered at the step of ``width`` (600,
        1200 or 2000 px on its long side); ``NotFound("No preview")`` when there is
        none, no render slot frees up within ``wait_s``, or not on macOS."""
        if self.platform != "darwin":
            raise NotFound(NO_PREVIEW)
        if not THUMB_MIN_WIDTH <= width <= THUMB_MAX_WIDTH:
            raise NotFound(NO_PREVIEW)
        width = thumb_step(width)
        name = f"{thumb_key(rec)}_{width}"
        folder = self.cache_dir / name
        cached = _cached_png(folder)
        if cached is not None:
            return cached
        with self._lock:
            if self._failed.get(name, 0) > time.monotonic():
                raise NotFound(NO_PREVIEW)
        path = self._file(rec, NO_PREVIEW)
        if not THUMB_SEMAPHORE.acquire(timeout=self.wait_s):
            # both slots busy (slow renders): not this file's failure, nothing recorded
            log.info("no Quick Look slot for %s within %ss", rec.path, self.wait_s)
            raise NotFound(NO_PREVIEW)
        try:
            cached = _cached_png(folder)  # rendered by another request while we waited?
            if cached is not None:
                return cached
            folder.mkdir(parents=True, exist_ok=True)
            args = [QLMANAGE, "-t", "-s", str(width), "-o", str(folder), str(path)]
            try:
                self.runner(args, self.timeout_s)
            except subprocess.TimeoutExpired:
                log.warning("Quick Look timed out on %s", rec.path)
            except (OSError, subprocess.SubprocessError):
                log.warning("Quick Look failed on %s", rec.path, exc_info=True)
            png = _cached_png(folder)
        finally:
            THUMB_SEMAPHORE.release()
        if png is None:
            self._remember_failure(name)
            raise NotFound(NO_PREVIEW)
        return png

    def _remember_failure(self, name: str) -> None:
        now = time.monotonic()
        with self._lock:
            # expired entries go first, so the map never outgrows the recent failures
            self._failed = {k: t for k, t in self._failed.items() if t > now}
            self._failed[name] = now + FAILED_TTL_S

    # -- text ---------------------------------------------------------------------

    def text(self, rec: FileRecord, max_bytes: int = TEXT_MAX_BYTES) -> tuple[str, bool]:
        """The first ``max_bytes`` (at most 200 KB) of a text-like file as UTF-8 (bad
        bytes replaced; a character cut at the limit dropped) and whether there was
        more. ``NotFound`` for other file types."""
        if (rec.ext or "") not in TEXT_EXTS:
            raise NotFound(f"No text preview for {rec.name}")
        max_bytes = max(1, min(max_bytes, TEXT_MAX_BYTES))
        path = self._file(rec, f"no text preview for {rec.name}")
        try:
            with open(path, "rb") as fh:
                data = fh.read(max_bytes + 1)
        except OSError as exc:
            raise NotFound(f"Cannot read {rec.name}") from exc
        truncated = len(data) > max_bytes
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        return decoder.decode(data[:max_bytes], final=not truncated), truncated
