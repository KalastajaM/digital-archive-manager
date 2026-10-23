"""Filing codes as the strongest suggestion source: what a file's codes set wins over
the rules and similar files; what they leave unset keeps the earlier suggestion."""

import dataclasses
from datetime import date
from typing import Protocol

from dam.config import SpecialFolders
from dam.core.naming import matches_convention
from dam.index.repo import FileRecord, FileRepo
from dam.rules.engine import CodeHit, Suggestion, TemplateError, _render_folder, _render_name

from .model import FilingCode

__all__ = ["CodeHit", "apply_codes", "codes_for"]


class _HasRepo(Protocol):
    repo: FileRepo


def codes_for(app_or_repo: _HasRepo | FileRepo, rec: FileRecord) -> list[CodeHit]:
    """The codes found for ``rec``: the code whose inbox folder holds it (pen marks and
    QR stickers join here later)."""
    repo = app_or_repo if isinstance(app_or_repo, FileRepo) else app_or_repo.repo
    hits: list[CodeHit] = []
    code = repo.inbox_code_of(rec.path)
    if code is not None:
        hits.append(CodeHit(code, "folder"))
    return hits


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

    for hit in hits:
        fc = codes.get(hit.code.upper())
        if fc is None:
            continue
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
