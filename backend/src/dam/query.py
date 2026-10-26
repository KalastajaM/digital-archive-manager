"""The search box language: plain words plus ``name:value`` filters.

``parse_query`` is the one place the text is taken apart. Plain words stay full-text
search; a token that starts with a known filter name and a colon (``tag:insurance``,
``in:"50. Medical"``, ``-tag:paid``) becomes a ``Filter``. Anything else, including a
colon after an unknown name (``http://example.org``), is a plain word. A value with
spaces is quoted. Values that cannot be right (a bad date, an unknown ``is:`` value) raise
``QueryError`` (a 400 in the API); whether a tag, collection or tray exists is not checked
here: nothing matches an unknown one.
"""

import re
from dataclasses import dataclass
from datetime import date

from dam.services.errors import InvalidRequest

FILTER_NAMES = (
    "name",
    "in",
    "tag",
    "collection",
    "from",
    "for",
    "type",
    "date",
    "before",
    "after",
    "tray",
    "is",
)

IS_VALUES = ("starred", "important", "locked", "todo", "note", "summary", "disconnected")

# kind of file -> extensions (lower case, no dot); any other word is taken as an extension
TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "image": ("jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "tif", "tiff", "bmp", "svg"),
    "doc": ("doc", "docx", "odt", "rtf", "pages"),
    "sheet": ("xls", "xlsx", "ods", "csv", "numbers"),
    "slides": ("ppt", "pptx", "odp", "key"),
    "text": ("txt", "md", "log"),
    "mail": ("eml", "msg"),
    "archive": ("zip", "7z", "rar", "tar", "gz"),
    "audio": ("mp3", "m4a", "wav", "flac", "aac", "ogg"),
    "video": ("mp4", "mov", "m4v", "avi", "mkv", "webm"),
}

_EXTENSION = re.compile(r"[a-z0-9]{1,10}")
_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", re.ASCII)


class QueryError(InvalidRequest):
    """The search text has a filter with a value that cannot be right."""


@dataclass(frozen=True)
class Filter:
    name: str  # one of FILTER_NAMES
    value: str
    negated: bool = False


@dataclass
class ParsedQuery:
    words: str  # the plain words, single-spaced
    filters: list[Filter]


def extensions_of(value: str) -> tuple[str, ...]:
    """The extensions a ``type:`` value stands for (a group, else the extension itself)."""
    key = value.strip().lower().lstrip(".")
    if key == "pdf":
        return ("pdf",)
    return TYPE_GROUPS.get(key, (key,))


def date_span(value: str) -> tuple[date, date]:
    """``[first day, day after the last)`` of ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``.
    ``QueryError`` for anything else, or a date that does not exist."""
    m = _DATE.fullmatch(value.strip())
    if m is None:
        raise QueryError(f"{value!r} is not a date. Use YYYY, YYYY-MM or YYYY-MM-DD.")
    year, month, day = int(m[1]), m[2], m[3]
    try:
        if day is not None:
            first = date(year, int(month), int(day))
            return first, date.fromordinal(first.toordinal() + 1)
        if month is not None:
            first = date(year, int(month), 1)
            nxt = date(year + 1, 1, 1) if int(month) == 12 else date(year, int(month) + 1, 1)
            return first, nxt
        return date(year, 1, 1), date(year + 1, 1, 1)
    except ValueError:
        raise QueryError(f"{value!r} is not a real date.") from None


def _check(name: str, value: str) -> str:
    """The value as the filter uses it; ``QueryError`` if it cannot be right."""
    value = value.strip()
    if not value:
        raise QueryError(f"{name}: needs a value, for example {name}:...")
    if name in ("date", "before", "after"):
        date_span(value)
    elif name == "is":
        value = value.lower()
        if value not in IS_VALUES:
            raise QueryError(f"is:{value} is not known. Use one of: {', '.join(IS_VALUES)}.")
    elif name == "type":
        value = value.lower().lstrip(".")
        if value not in TYPE_GROUPS and not _EXTENSION.fullmatch(value):
            raise QueryError(f"type:{value} is not a file type. Use an extension or a group.")
    return value


def _filter_head(text: str, i: int) -> tuple[bool, str, int] | None:
    """At ``text[i]``: ``(negated, name, index after the colon)`` when a known filter
    starts there, else None."""
    j = i
    negated = text[j] == "-"
    if negated:
        j += 1
    k = j
    while k < len(text) and text[k].isalpha():
        k += 1
    name = text[j:k].lower()
    if name in FILTER_NAMES and k < len(text) and text[k] == ":":
        return negated, name, k + 1
    return None


def parse_query(text: str) -> ParsedQuery:
    """Split the search text into plain words and filters (see the module doc)."""
    words: list[str] = []
    filters: list[Filter] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        head = _filter_head(text, i)
        if head is None:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            words.append(text[i:j].strip('"'))  # a quoted phrase is words, as before
            i = j
            continue
        negated, name, j = head
        if j < n and text[j] == '"':
            close = text.find('"', j + 1)
            end = n if close < 0 else close
            value, i = text[j + 1 : end], min(n, end + 1)
        else:
            end = j
            while end < n and not text[end].isspace():
                end += 1
            value, i = text[j:end], end
        filters.append(Filter(name, _check(name, value), negated))
    return ParsedQuery(" ".join(w for w in words if w), filters)


def format_filter(f: Filter) -> str:
    """The filter as it is typed: quoted when the value has spaces or quotes."""
    value = f.value
    if not value or any(c.isspace() or c == '"' for c in value):
        value = '"' + value.replace('"', "") + '"'
    return f"{'-' if f.negated else ''}{f.name}:{value}"
