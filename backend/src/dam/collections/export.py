"""Export a collection as a zip or one combined PDF.

Exports are built under ``cache_dir/exports/<uuid hex>/`` and never inside the archive.
``prune_exports`` is the only remover here (pinned in the AST no-delete test).
"""

from __future__ import annotations

import io
import logging
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pypdfium2
from PIL import Image, ImageDraw, ImageFont

from dam.config import AppPaths
from dam.core.fs import resolve
from dam.core.paths import ArchivePaths, nfc
from dam.index.content import MAX_BYTES
from dam.index.repo import FileRecord
from dam.pdfium import PDFIUM_LOCK
from dam.services.errors import InvalidRequest, NotFound

log = logging.getLogger(__name__)

LARGE_EXPORT_BYTES = 200 * 1024 * 1024
PDF_CEILING_BYTES = 1024**3  # hard limit on PDF + image members of a combined PDF
READ_TIMEOUT_S = 60.0  # a read that delivers nothing for this long is a stuck download
EXPORT_DEADLINE_S = 600.0  # the whole export
MAX_PAGES = 2000
MAX_IMAGE_PIXELS = 50_000_000
MAX_NAME = 100
PRUNE_AFTER_S = 86400
SF_DATALESS = 0x40000000
A4_W, A4_H = 1240, 1754  # A4 at 150 dpi
_MARGIN = 100
_TEXT_EXTS = {"txt", "csv", "xml"}
_IMAGE_EXTS = {"jpg", "jpeg", "png"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_EXPORT_DIR = re.compile(r"^[0-9a-f]{32}$")
_NOT_DOWNLOADED = "not downloaded — open it once in Finder, then export again"
_TIME_LIMIT = "export time limit reached"


def estimate_size(files: list[FileRecord]) -> int:
    return sum(f.size or 0 for f in files)


def safe_name(name: str) -> str:
    cleaned = _CTRL.sub("_", name.replace("/", "_").replace("\\", "_")).strip()
    return cleaned[:MAX_NAME].strip() or "export"


def _plain(text: str) -> str:
    return _CTRL.sub("?", text)


# --- export cache -----------------------------------------------------------------


def _exports_root(app_paths: AppPaths, archive_root: Path | None = None) -> Path:
    """The resolved export cache folder, created on demand. With ``archive_root`` it is
    refused (before anything is created) when it lies inside the archive or contains it."""
    root = app_paths.cache_dir / "exports"
    if root.is_symlink():
        raise InvalidRequest(
            "The export folder cannot be a shortcut. Remove the shortcut and try again."
        )
    resolved = resolve(root)
    if archive_root is not None:
        arch = resolve(archive_root)
        if resolved == arch or arch in resolved.parents or resolved in arch.parents:
            raise InvalidRequest("The export folder must be outside the archive.")
    root.mkdir(parents=True, exist_ok=True)
    return resolved


def _is_export_child(root: Path, path: Path) -> bool:
    """True when ``path`` resolves to a direct child of ``root`` (strictly inside)."""
    resolved, base = resolve(path), resolve(root)
    return resolved != base and resolved.parent == base


def prune_exports(app_paths: AppPaths, older_than_s: float = PRUNE_AFTER_S) -> list[str]:
    """Remove export folders older than ``older_than_s``; returns the removed names.

    Only real (non-symlink) folders named like an export id, directly inside the
    resolved ``cache_dir/exports``, are removed."""
    root = _exports_root(app_paths)
    cutoff = time.time() - older_than_s
    removed: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or not _EXPORT_DIR.match(entry.name):
            continue
        try:
            if entry.stat().st_mtime >= cutoff or not _is_export_child(root, entry):
                continue
            shutil.rmtree(resolve(entry))
            removed.append(entry.name)
        except OSError:
            log.warning("could not prune export %s", entry, exc_info=True)
    return removed


def _new_export_dir(app_paths: AppPaths, paths: ArchivePaths) -> Path:
    # exports live in the main folder only
    root = _exports_root(app_paths, paths.root)
    try:
        prune_exports(app_paths)
    except (InvalidRequest, OSError):
        log.warning("pruning old exports failed", exc_info=True)
    out = root / uuid.uuid4().hex
    out.mkdir()
    return out


def _check_size(files: list[FileRecord], confirm_large: bool) -> None:
    if estimate_size(files) > LARGE_EXPORT_BYTES and not confirm_large:
        raise InvalidRequest("This export is larger than 200 MB. Confirm to continue.")


# --- reading ----------------------------------------------------------------------


class _Skip(Exception):
    """A member that cannot go into the export; ``str(exc)`` is the reason."""


def _is_dataless(path: Path) -> bool:
    """A Drive file that is evicted (macOS SF_DATALESS): reading it would download it."""
    return bool(getattr(os.stat(path), "st_flags", 0) & SF_DATALESS)


def _precheck(paths: ArchivePaths, rec: FileRecord) -> tuple[Path, int]:
    """Locate the member and return (path, real size), or raise ``_Skip``."""
    try:
        path = paths.abs(rec.path)
    except Exception:
        raise _Skip("could not read (outside the archive)") from None
    try:
        size = path.stat().st_size
        if _is_dataless(path):
            raise _Skip(_NOT_DOWNLOADED)
    except FileNotFoundError:
        raise _Skip("could not read (file not found)") from None
    except OSError as exc:
        raise _Skip(f"could not read ({exc.strerror or type(exc).__name__})") from None
    if size > MAX_BYTES:
        raise _Skip("too large")
    return path, size


def _chunks(path: Path, timeout_s: float, deadline: float) -> Iterator[bytes]:
    """Yield the file in chunks, read by a daemon worker. A read that stalls for
    ``timeout_s`` (a cloud file that never downloads) or runs past the export deadline
    ends in ``_Skip``; the worker notices the abandonment at its next chunk."""
    q: queue.Queue = queue.Queue(maxsize=4)
    seen = 0
    abandoned = threading.Event()

    def put(item: object) -> None:
        while not abandoned.is_set():
            try:
                q.put(item, timeout=0.1)
                return
            except queue.Full:
                pass

    def work() -> None:
        try:
            with open(path, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    put(chunk)
                    if abandoned.is_set():
                        return
            put(None)
        except BaseException as exc:  # handed to the consumer
            put(exc)

    threading.Thread(target=work, name="export-read", daemon=True).start()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Skip(_TIME_LIMIT)
            try:
                item = q.get(timeout=min(timeout_s, remaining))
            except queue.Empty:
                if deadline - time.monotonic() <= 0:
                    raise _Skip(_TIME_LIMIT) from None
                raise _Skip("could not read (not downloaded)") from None
            if item is None:
                return
            if isinstance(item, bytes):
                seen += len(item)
                if seen > MAX_BYTES:  # grew since the stat
                    raise _Skip("too large")
            if isinstance(item, FileNotFoundError):
                raise _Skip("could not read (file not found)")
            if isinstance(item, BaseException):
                raise _Skip(
                    f"could not read ({getattr(item, 'strerror', None) or type(item).__name__})"
                )
            yield item
    finally:
        abandoned.set()


@dataclass
class _Line:
    path: str
    size: int | None
    note: str = ""  # "" = included


def _arcname(rec: FileRecord) -> str:
    name = nfc(rec.path)
    parts = re.split(r"[/\\]", name)
    if "\\" in name or name.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise _Skip("unsafe name")
    return PurePosixPath(name).as_posix()


# --- zip --------------------------------------------------------------------------


def build_zip(
    app_paths: AppPaths,
    paths: ArchivePaths,
    files: list[FileRecord],
    name: str,
    *,
    confirm_large: bool = False,
    read_timeout_s: float = READ_TIMEOUT_S,
    export_deadline_s: float = EXPORT_DEADLINE_S,
) -> Path:
    return build_zip_with_notes(
        app_paths,
        paths,
        files,
        name,
        confirm_large=confirm_large,
        read_timeout_s=read_timeout_s,
        export_deadline_s=export_deadline_s,
    )[0]


def build_zip_with_notes(
    app_paths: AppPaths,
    paths: ArchivePaths,
    files: list[FileRecord],
    name: str,
    *,
    confirm_large: bool = False,
    read_timeout_s: float = READ_TIMEOUT_S,
    export_deadline_s: float = EXPORT_DEADLINE_S,
) -> tuple[Path, list[str]]:
    """``build_zip``, plus the ``"<path>: not included: <reason>"`` notes of every member
    left out (as ``build_pdf`` returns them)."""
    _check_size(files, confirm_large)
    out = _new_export_dir(app_paths, paths) / f"{safe_name(name)}.zip"
    deadline = time.monotonic() + export_deadline_s
    lines: list[_Line] = []
    seen = {"contents.txt"}
    with zipfile.ZipFile(out, "w", allowZip64=True) as zf:
        for rec in files:
            line = _Line(_plain(nfc(rec.path)), rec.size)
            lines.append(line)
            try:
                arc = _arcname(rec)
                if arc.casefold() in seen:
                    raise _Skip(
                        "name clashes with contents.txt"
                        if arc.casefold() == "contents.txt"
                        else "duplicate name"
                    )
                if time.monotonic() >= deadline:
                    raise _Skip(_TIME_LIMIT)
                path, _ = _precheck(paths, rec)
                _add_member(zf, arc, path, rec, read_timeout_s, deadline, line)
                seen.add(arc.casefold())
            except _Skip as skip:
                line.note = f"not included: {skip}"
        listing = "\n".join(
            f"{ln.path}\t{ln.size if ln.size is not None else '?'}"
            + (f"\t{_plain(ln.note)}" if ln.note else "")
            for ln in lines
        )
        zf.writestr("contents.txt", listing + "\n", compress_type=zipfile.ZIP_DEFLATED)
    return out, [f"{ln.path}: {ln.note}" for ln in lines if ln.note]


def _add_member(
    zf: zipfile.ZipFile,
    arc: str,
    path: Path,
    rec: FileRecord,
    timeout_s: float,
    deadline: float,
    line: _Line,
) -> None:
    # Spool to an anonymous temp file first, so a read that fails halfway leaves no
    # truncated entry in the zip.
    with tempfile.TemporaryFile() as spool:
        total = 0
        for chunk in _chunks(path, timeout_s, deadline):
            spool.write(chunk)
            total += len(chunk)
        spool.seek(0)
        info = zipfile.ZipInfo(arc, date_time=time.localtime()[:6])
        info.compress_type = (
            zipfile.ZIP_DEFLATED if (rec.ext or "").lower() in _TEXT_EXTS else zipfile.ZIP_STORED
        )
        info.file_size = total
        with zf.open(info, "w") as dest:
            shutil.copyfileobj(spool, dest, 1 << 20)
    line.size = total


# --- combined PDF -----------------------------------------------------------------


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _wrap(text: str, font, max_w: float) -> list[str]:
    """Wrap on character boundaries (paths have few spaces)."""
    rows: list[str] = []
    cur = ""
    for ch in _plain(text):
        if cur and font.getlength(cur + ch) > max_w:
            rows.append(cur)
            cur = ch
        else:
            cur += ch
    rows.append(cur)
    return rows


_BODY_SIZE, _HEAD_SIZE, _GAP = 26, 40, 12
_LINE_H = int(_BODY_SIZE * 1.25)
_PAGE_LIMIT_Y = A4_H - _MARGIN


def _head_rows(title: str) -> list[str]:
    return _wrap(f"Contents: {title}", _font(_HEAD_SIZE), A4_W - 2 * _MARGIN)


def _first_y(head_rows: list[str]) -> int:
    return _MARGIN + len(head_rows) * int(_HEAD_SIZE * 1.3) + 20


def _entry_rows(number: int, path: str, note: str) -> list[str]:
    font, max_w = _font(_BODY_SIZE), A4_W - 2 * _MARGIN
    rows = _wrap(f"{number}. {path}", font, max_w)
    if note:
        rows += _wrap(f"    {note}", font, max_w)
    return rows


def _layout(row_counts: list[int], first_y: int) -> list[list[int]]:
    """Which entries go on which contents page. Pure arithmetic (no drawing), so page
    counts can be probed cheaply; ``_render_contents`` draws exactly this layout."""
    pages: list[list[int]] = [[]]
    y = first_y
    for i, n in enumerate(row_counts):
        if y + n * _LINE_H > _PAGE_LIMIT_Y and pages[-1]:
            pages.append([])
            y = _MARGIN
        pages[-1].append(i)
        y += n * _LINE_H + _GAP
    return pages


def _render_contents(
    head_rows: list[str], entry_rows: list[list[str]], layout: list[list[int]]
) -> list[Image.Image]:
    body, head = _font(_BODY_SIZE), _font(_HEAD_SIZE)
    images: list[Image.Image] = []
    for page_no, members in enumerate(layout):
        im = Image.new("RGB", (A4_W, A4_H), "white")
        d = ImageDraw.Draw(im)
        y = _MARGIN
        if page_no == 0:
            for row in head_rows:
                d.text((_MARGIN, y), row, fill="black", font=head)
                y += int(_HEAD_SIZE * 1.3)
            y += 20
        for i in members:
            for row in entry_rows[i]:
                d.text((_MARGIN, y), row, fill="black", font=body)
                y += _LINE_H
            y += _GAP
        images.append(im)
    return images


def _pages_to_pdf_bytes(pages: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return buf.getvalue()


def _image_page_pdf(data: bytes) -> bytes:
    """One A4 page holding the image, scaled to fit with its aspect ratio kept."""
    try:
        with Image.open(io.BytesIO(data)) as src:
            if src.width * src.height > MAX_IMAGE_PIXELS:
                raise _Skip("image too large")
            src.load()
            if src.mode in ("RGBA", "LA", "P"):
                rgba = src.convert("RGBA")
                im = Image.new("RGB", rgba.size, "white")
                im.paste(rgba, mask=rgba.getchannel("A"))
            else:
                im = src.convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _Skip("image too large") from None
    except _Skip:
        raise
    except Exception:
        raise _Skip("could not read (not a valid image)") from None
    scale = min((A4_W - 2 * 40) / im.width, (A4_H - 2 * 40) / im.height)
    new = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))))
    page = Image.new("RGB", (A4_W, A4_H), "white")
    page.paste(new, ((A4_W - new.width) // 2, (A4_H - new.height) // 2))
    return _pages_to_pdf_bytes([page])


def build_pdf(
    app_paths: AppPaths,
    paths: ArchivePaths,
    files: list[FileRecord],
    name: str,
    *,
    confirm_large: bool = False,
    read_timeout_s: float = READ_TIMEOUT_S,
    export_deadline_s: float = EXPORT_DEADLINE_S,
) -> tuple[Path, list[str]]:
    """Merge the PDF (and image) members, a contents page first. Returns the file and the
    "<path>: <reason>" notes of every member left out."""
    _check_size(files, confirm_large)
    out = _new_export_dir(app_paths, paths) / f"{safe_name(name)}.pdf"
    deadline = time.monotonic() + export_deadline_s
    lines: list[_Line] = []
    spans: list[tuple[_Line, int, int]] = []  # included members: (line, first page, pages)
    body = pypdfium2.PdfDocument.new()
    try:
        used_bytes = 0
        for rec in files:
            line = _Line(nfc(rec.path), rec.size)
            lines.append(line)
            ext = (rec.ext or "").lower()
            try:
                if ext != "pdf" and ext not in _IMAGE_EXTS:
                    raise _Skip("file type is not included in a PDF")
                if time.monotonic() >= deadline:
                    raise _Skip(_TIME_LIMIT)
                if len(body) >= MAX_PAGES - 1:  # no room left, not even for contents
                    raise _Skip("page limit")
                path, size = _precheck(paths, rec)
                if used_bytes + size > PDF_CEILING_BYTES:
                    raise _Skip("size limit for a combined PDF — use zip")
                data = b"".join(_chunks(path, read_timeout_s, deadline))
                used_bytes += len(data)
                if ext in _IMAGE_EXTS:
                    data = _image_page_pdf(data)
                first = len(body)
                added = _append_pdf(body, data)
                spans.append((line, first, added))
                line.note = f"{added} page{'s' if added != 1 else ''}"
            except _Skip as skip:
                line.note = f"not included: {skip}"
        pages = _fit_pages(name, lines, spans, body)
        contents = _pages_to_pdf_bytes(pages)
        with PDFIUM_LOCK:
            cdoc = pypdfium2.PdfDocument(contents)
            try:
                body.import_pages(cdoc, index=0)
            finally:
                cdoc.close()
            body.save(out)
    finally:
        with PDFIUM_LOCK:
            body.close()
    notes = [f"{ln.path}: {ln.note}" for ln in lines if ln.note.startswith("not included")]
    return out, notes


def _fit_pages(
    title: str,
    lines: list[_Line],
    spans: list[tuple[_Line, int, int]],
    body: pypdfium2.PdfDocument,
) -> list[Image.Image]:
    """Trim trailing members so that contents pages + member pages fit ``MAX_PAGES``
    exactly, then render the contents pages once. The fit is found by binary search over
    pure layouts (no drawing)."""
    head = _head_rows(title)
    first_y = _first_y(head)
    span_of = {id(line): j for j, (line, _, _) in enumerate(spans)}
    kept_rows = [_entry_rows(i + 1, ln.path, ln.note) for i, ln in enumerate(lines)]
    trimmed_rows = {
        j: _entry_rows(i + 1, ln.path, "not included: page limit")
        for i, ln in enumerate(lines)
        if (j := span_of.get(id(ln))) is not None
    }
    counts = [len(r) for r in kept_rows]
    trimmed_counts = {j: len(r) for j, r in trimmed_rows.items()}
    prefix = [0]
    for _, _, n in spans:
        prefix.append(prefix[-1] + n)

    def total(k: int) -> int:
        rows = [
            trimmed_counts[span_of[id(ln)]] if id(ln) in span_of and span_of[id(ln)] >= k else c
            for ln, c in zip(lines, counts, strict=True)
        ]
        return len(_layout(rows, first_y)) + prefix[k]

    n = len(spans)
    k = n
    if total(n) > MAX_PAGES:
        lo, hi = 0, n - 1  # largest k that fits, assuming fewer members never need more
        k = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if total(mid) <= MAX_PAGES:
                k, lo = mid, mid + 1
            else:
                hi = mid - 1
    if k >= 0:
        _drop_spans(lines, spans, body, k)
        rows = [
            trimmed_rows[span_of[id(ln)]] if id(ln) in span_of and span_of[id(ln)] >= k else r
            for ln, r in zip(lines, kept_rows, strict=True)
        ]
        return _render_contents(head, rows, _layout([len(r) for r in rows], first_y))
    # even the contents alone do not fit: no members, contents cut to MAX_PAGES
    _drop_spans(lines, spans, body, 0)
    rows = [
        trimmed_rows[span_of[id(ln)]] if id(ln) in span_of else r
        for ln, r in zip(lines, kept_rows, strict=True)
    ]
    shown = len(rows)
    while True:
        more = len(rows) - shown
        listed = [*rows[:shown], [f"... and {more} more"]] if more else rows[:shown]
        layout = _layout([len(r) for r in listed], first_y)
        if len(layout) <= MAX_PAGES:
            return _render_contents(head, listed, layout)
        shown -= max(1, len(listed) - sum(len(p) for p in layout[:MAX_PAGES]))


def _drop_spans(
    lines: list[_Line],
    spans: list[tuple[_Line, int, int]],
    body: pypdfium2.PdfDocument,
    keep: int,
) -> None:
    """Remove the pages of every included member after the first ``keep`` and mark them."""
    if keep >= len(spans):
        return
    first_dropped = spans[keep][1]
    with PDFIUM_LOCK:
        for idx in range(len(body) - 1, first_dropped - 1, -1):
            body.del_page(idx)
    for line, _, _ in spans[keep:]:
        line.note = "not included: page limit"


def _append_pdf(body: pypdfium2.PdfDocument, data: bytes) -> int:
    """Append all pages of a PDF; raises ``_Skip`` for encrypted/corrupt files. Returns
    the number of pages added."""
    with PDFIUM_LOCK:
        try:
            src = pypdfium2.PdfDocument(data)
        except pypdfium2.PdfiumError as exc:
            msg = str(exc).lower()
            raise _Skip(
                "encrypted (password protected)"
                if "password" in msg
                else "could not read (corrupt PDF)"
            ) from None
        try:
            n = len(src)
            if n == 0:
                raise _Skip("could not read (no pages)")
            try:
                body.import_pages(src, index=len(body))
            except pypdfium2.PdfiumError:
                raise _Skip("could not read (corrupt PDF)") from None
            return n
        finally:
            src.close()


# --- one collection, for the interfaces ----------------------------------------------

_NOTE_SEP = ": not included: "
_MEDIA_TYPES = {".zip": "application/zip", ".pdf": "application/pdf"}


@dataclass
class NotIncluded:
    path: str
    reason: str


@dataclass
class ExportResult:
    """``token`` names the export (``export_file``); None with ``needs_confirm`` when
    the export is over ``LARGE_EXPORT_BYTES`` and was not confirmed (nothing built;
    ``size`` is then the estimate). Otherwise ``size`` is the built file's size."""

    token: str | None
    size: int
    needs_confirm: bool = False
    not_included: list[NotIncluded] = field(default_factory=list)


def split_note(note: str) -> NotIncluded:
    """``"<path>: not included: <reason>"`` -> its parts (the reason never holds the
    separator; a path might, so the last one splits)."""
    path, sep, reason = note.rpartition(_NOTE_SEP)
    return NotIncluded(path, reason) if sep else NotIncluded(note, "not included")


def export_collection(
    app_paths: AppPaths,
    paths: ArchivePaths,
    files: list[FileRecord],
    name: str,
    fmt: str,
    confirm_large: bool,
) -> ExportResult:
    """Build ``files`` (a collection's ``expand``) as ``fmt`` ("zip" | "pdf") named
    ``name``, in the request's thread (bounded by ``EXPORT_DEADLINE_S``)."""
    if fmt not in ("zip", "pdf"):
        raise InvalidRequest("Choose zip or pdf as the export format.")
    estimate = estimate_size(files)
    if estimate > LARGE_EXPORT_BYTES and not confirm_large:
        return ExportResult(None, estimate, needs_confirm=True)
    build = build_zip_with_notes if fmt == "zip" else build_pdf
    out, notes = build(app_paths, paths, files, name, confirm_large=True)
    return ExportResult(out.parent.name, out.stat().st_size, False, [split_note(n) for n in notes])


def export_file(app_paths: AppPaths, token: str) -> tuple[Path, str]:
    """The built file of export ``token`` and its media type; ``NotFound`` for a token
    that is not an export id, an export that is gone (pruned), or anything odd in its
    folder (not exactly one regular file, a symlink)."""
    if not isinstance(token, str) or not _EXPORT_DIR.fullmatch(token):
        raise NotFound("That export is not available.")
    root = _exports_root(app_paths)
    folder = root / token
    if folder.is_symlink() or not folder.is_dir() or not _is_export_child(root, folder):
        raise NotFound("That export is no longer available. Exports are kept for a day.")
    entries = list(folder.iterdir())
    if len(entries) != 1:
        raise NotFound("That export is not available.")
    path = entries[0]
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if path.is_symlink() or not path.is_file() or media_type is None:
        raise NotFound("That export is not available.")
    return path, media_type
