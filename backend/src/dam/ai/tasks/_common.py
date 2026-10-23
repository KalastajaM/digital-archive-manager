"""What the document tasks share: the file to send, the language, the cache key."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from dam.ai import guard
from dam.index.repo import FileRecord
from dam.ops.guards import is_under
from dam.services.errors import InvalidRequest, NotFound

if TYPE_CHECKING:
    from dam.app import App

LANGUAGES = {
    "en": "English",
    "fi": "Finnish",
    "sv": "Swedish",
    "nl": "Dutch",
    "de": "German",
}

NAMING = (
    "File names follow the archive convention YYYYMMDD_Description: the document's own "
    "date (when it was issued), then a short description with words joined by "
    "underscores, then the original extension. Keep the document's proper names "
    "(company names, Finnish terms) as they appear in it."
)


def language(app: "App") -> str:
    """The output language's name (``ai.language``, spec §7.1), e.g. "English"."""
    code = (app.settings.ai.language or "en").strip()
    return LANGUAGES.get(code.casefold(), code)


def shorten(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters at a word boundary, ending in "…"."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + "…"


def digest(value: Any) -> str:
    """A stable sha256 of a JSON-able value (a cache key part)."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return sha256(raw.encode()).hexdigest()


def rules_point_excluded(app: "App", rec: FileRecord) -> str | None:
    """Why an inbox file is never sent: the rules would file it under an excluded
    folder, so it is probably that kind of document (spec §2.3); else None.

    ``Suggestion.folder`` is the folder of the FIRST matching rule (in rule-file order)
    that names one; later matching rules' folders are not looked at, just as filing
    would never use them. When a filing code replaced that folder, both the earlier
    folder and the code's are checked: a code never makes such a file sendable."""
    if not is_under(rec.path, app.settings.special_folders.inbox, strict=True):
        return None
    found = app.inbox.suggestion(rec.drive_id)
    for folder in (found.folder_before_codes, found.folder):
        hit = guard.excluded_folder(folder, app.settings.ai.exclude_folders) if folder else None
        if hit is not None:
            return (
                f"{rec.name}: the rules suggest {folder}, an excluded folder ({hit}); "
                "it is never sent"
            )
    return None


@dataclass(frozen=True)
class Source:
    """The file a document task is about. ``excluded`` is the excluded folder it is
    in (then ``text`` is never read); ``blocked`` why the task refuses it."""

    record: FileRecord
    text: str
    excluded: str | None
    blocked: str | None


def source(app: "App", params: dict[str, Any]) -> Source:
    drive_id = params.get("drive_id")
    if not isinstance(drive_id, str) or not drive_id:
        raise InvalidRequest("drive_id is required")
    rec = app.repo.get(drive_id)
    if rec is None or rec.missing or rec.parked_at is not None or rec.is_dir or rec.is_link:
        raise NotFound(drive_id[:80])
    exclude = app.settings.ai.exclude_folders
    excluded = guard.excluded_folder(rec.path, exclude)
    if excluded is not None:
        # the service refuses it by its files (and says why); its text is never read
        return Source(rec, "", excluded, None)
    text = app.repo.text_for(drive_id)
    blocked = rules_point_excluded(app, rec)
    if blocked is not None:
        return Source(rec, "", None, blocked)  # nothing to show: it would not go out
    if not text.strip():
        return Source(rec, "", None, f"no text was found in {rec.name}")
    return Source(rec, guard.cut(text, guard.DOC_CHARS), None, None)
