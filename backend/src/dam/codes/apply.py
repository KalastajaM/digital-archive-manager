"""Filing codes as the strongest suggestion source: what a file's codes set wins over
the rules and similar files; what they leave unset keeps the earlier suggestion."""

import dataclasses
from collections.abc import Collection
from datetime import date
from typing import Protocol

from dam.config import SpecialFolders
from dam.core.naming import matches_convention
from dam.index.repo import FileRecord, FileRepo
from dam.rules.engine import CodeHit, Suggestion, TemplateError, _render_folder, _render_name

from .model import FilingCode
from .qr_model import QrRead

__all__ = ["CodeHit", "apply_codes", "apply_ticks", "codes_for", "known_reads", "unclear_boxes"]


class _HasRepo(Protocol):
    repo: FileRepo


def codes_for(
    app_or_repo: _HasRepo | FileRepo,
    rec: FileRecord,
    known: Collection[str] | None = None,
    qr: list[QrRead] | None = None,
) -> list[CodeHit]:
    """The codes found for ``rec``: the code whose inbox folder holds it, then one hit
    per code read from a QR sticker on an inbox file (``qr``: the file's reads, else
    read from the index). A sticker code not in ``known`` (the loaded table, compared
    case-insensitively) is ignored; without ``known`` none is. A code found in the
    folder and on a sticker is one code with two hits."""
    repo = app_or_repo if isinstance(app_or_repo, FileRepo) else app_or_repo.repo
    hits: list[CodeHit] = []
    code = repo.inbox_code_of(rec.path)
    if code is not None:
        hits.append(CodeHit(code, "folder"))
    for read in known_reads(repo, rec, known, qr):
        if not any(h.via == "qr" and h.code == read.code.upper() for h in hits):
            hits.append(CodeHit(read.code.upper(), "qr", raw=read.code))
    return hits


def known_reads(
    repo: FileRepo,
    rec: FileRecord,
    known: Collection[str] | None,
    qr: list[QrRead] | None = None,
) -> list[QrRead]:
    """The file's QR reads whose code is known (``known``, folded to upper case); none
    for a file outside the inbox: a sticker on a filed document routes nothing."""
    if known is None or not repo.in_inbox_path(rec.path):
        return []
    upper = {k.upper() for k in known}
    reads = repo.qr_for(rec.drive_id) if qr is None else qr
    return [r for r in reads if r.code.upper() in upper]


def apply_ticks(found: Suggestion, reads: list[QrRead]) -> Suggestion:
    """``found`` with ``star``/``important`` from the stickers' tick boxes (``reads``:
    known codes only). A box ticked on any sticker gives True; else unclear on any
    gives None and ``marks_unclear``; else empty on every boxed sticker gives False.
    No boxed sticker leaves both None."""
    boxed = [r for r in reads if r.star is not None or r.important is not None]
    if not boxed:
        return found

    def tick(values: list[str | None]) -> bool | None:
        if "ticked" in values:
            return True
        if "unclear" in values or None in values:
            return None
        return False

    star = tick([r.star for r in boxed])
    important = tick([r.important for r in boxed])
    return dataclasses.replace(
        found, star=star, important=important, marks_unclear=star is None or important is None
    )


def unclear_boxes(found: Suggestion) -> list[str]:
    """The tick boxes ("star", "important") a sticker has but could not be read."""
    if not found.marks_unclear:
        return []
    return [k for k in ("star", "important") if getattr(found, k) is None]


# an ``as_suggested`` code's tray in the conflict check: "no tray" (``Suggestion.tray``
# becomes None)
NO_TRAY = "\0no tray"


def source_of(code: str) -> str:
    return f"code:{code}"


def apply_codes(
    found: Suggestion,
    hits: list[CodeHit],
    codes: dict[str, FilingCode],
    doc_date: date | None,
    stem: str,
    ext: str,
    special: SpecialFolders,
) -> Suggestion:
    """``found`` with each field the hit codes set (source ``code:<CODE>``). Tags and
    collections are united; for the folder, name and tray the first code wins and a
    different value from a later code sets ``conflict``. A code whose template does not
    render for this file sets nothing for that field (source noted with " (template
    error)"). A code not in ``codes`` sets nothing. An ``as_suggested`` code ("already
    handled") keeps the suggested folder and name but sets "no tray": the tray becomes
    None (source ``code:<CODE>``), and with a code that names a tray it is a conflict.
    Its tags and collections are added like any code's.

    As in the rules engine, a code's name template is not used when the suggested name
    already follows the naming convention (it would add the date twice). When a code
    sets the tray, ``payee`` deliberately stays as the rules and the scan found it: a
    code names no payee, and the detected one is still the best prefill.
    ``folder_before_codes`` keeps the earlier folder for the AI exclusion guard."""
    out = dataclasses.replace(
        found,
        tags=list(found.tags),
        sources=list(found.sources),
        tag_sources=dict(found.tag_sources),
        collections=list(found.collections),
        collection_sources=dict(found.collection_sources),
        codes=[*found.codes, *hits],
        folder_before_codes=found.folder,
    )
    conventional = matches_convention(found.name)
    suffix = f".{ext}" if ext else ""
    set_by_code: dict[str, str] = {}  # field -> the value the first code gave

    def put(key: str, value: str, code: str) -> None:
        if key in set_by_code:
            if set_by_code[key] != value:
                out.conflict = True
            return
        set_by_code[key] = value
        setattr(out, key, None if value == NO_TRAY else value)
        setattr(out, f"{key}_source", source_of(code))

    applied: set[str] = set()
    for hit in hits:
        fc = codes.get(hit.code.upper())
        # a code with several hits (folder and sticker) is applied once
        if fc is None or fc.code in applied:
            continue
        applied.add(fc.code)
        src = source_of(fc.code)
        errored = False
        if fc.as_suggested:
            # "file as suggested" means no tray: it clears a rule's or the scan's tray
            # and contradicts any tray code
            put("tray", NO_TRAY, fc.code)
        elif fc.folder is not None:
            try:
                put("folder", _render_folder(fc.folder, doc_date, stem, special), fc.code)
            except TemplateError:
                errored = True
        if fc.name is not None and not conventional and not fc.as_suggested:
            try:
                put("name", _render_name(fc.name, doc_date, stem, ext) + suffix, fc.code)
            except TemplateError:
                errored = True
        if fc.tray is not None and not fc.as_suggested:
            put("tray", fc.tray, fc.code)
        for tag in fc.tags:
            if tag not in out.tags:
                out.tags.append(tag)
                out.tag_sources[tag] = src
        for name in fc.collections:
            if name not in out.collections:
                out.collections.append(name)
                out.collection_sources[name] = src
        out.sources.append(src + (" (template error)" if errored else ""))
    return out
