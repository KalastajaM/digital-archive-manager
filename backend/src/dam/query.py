"""The search box language: plain words plus ``name:value`` filters.

``parse_query`` is the one place the text is taken apart. Plain words stay full-text
search; a token that starts with a known filter name and a colon (``tag:insurance``,
``in:"50. Medical"``, ``-tag:paid``) becomes a ``Filter``. Anything else, including a
colon after an unknown name (``http://example.org``), is a plain word. A value with
spaces is quoted; an unquoted value with commas is a list, any of which may match
(``type:pdf,docx``).

Words: every word must match. ``"two words"`` is a phrase, ``word*`` a prefix, and the
last word typed is a prefix too (the box searches while typing). ``-word`` or
``NOT word`` leaves out files with it, ``a OR b`` wants either (binding tighter than the
implicit AND), and ``AND`` is allowed and changes nothing. Only the upper-case forms are
operators: ``and``, ``or`` and ``not`` are words.

Values that cannot be right (a bad date, an unknown ``is:`` value) raise ``QueryError``
(a 400 in the API); whether a tag, collection or tray exists is not checked here: nothing
matches an unknown one.
"""

import re
from dataclasses import dataclass
from datetime import date

from dam.errors import InvalidRequest

FILTER_NAMES = (
    "name",
    "in",
    "tag",
    "collection",
    "from",
    "for",
    "id",
    "iban",
    "domain",
    "type",
    "date",
    "before",
    "after",
    "tray",
    "is",
)

IS_VALUES = ("starred", "important", "locked", "todo", "note", "summary", "changed", "disconnected")

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
    # an unquoted ``a,b``: the values any of which may match (``value`` is the text)
    any_of: tuple[str, ...] = ()

    @property
    def values(self) -> tuple[str, ...]:
        return self.any_of or (self.value,)


@dataclass(frozen=True)
class Term:
    """A plain word, or a phrase typed in quotes."""

    text: str
    phrase: bool = False
    prefix: bool = False  # ``word*``, or the last word typed


@dataclass
class ParsedQuery:
    clauses: list[list[Term]]  # every clause must match; a clause is terms joined by OR
    excluded: list[Term]  # ``-word`` / ``NOT word``: a file with any of them is left out
    filters: list[Filter]

    @property
    def words(self) -> str:
        """The wanted words and phrases, single-spaced."""
        return " ".join(t.text for clause in self.clauses for t in clause)


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


_OPERATORS = ("AND", "OR", "NOT")


def _filter_value(name: str, raw: str, quoted: bool) -> tuple[str, tuple[str, ...]]:
    """``(value, any_of)`` of a filter: an unquoted value with commas is a list."""
    if quoted or "," not in raw:
        return _check(name, raw), ()
    parts = [p for p in (p.strip() for p in raw.split(",")) if p]
    if not parts:
        raise QueryError(f"{name}: needs a value, for example {name}:...")
    values = tuple(dict.fromkeys(_check(name, p) for p in parts))
    return ",".join(values), values if len(values) > 1 else ()


def parse_query(text: str) -> ParsedQuery:
    """Split the search text into words and filters (see the module doc)."""
    clauses: list[list[Term]] = []
    excluded: list[Term] = []
    filters: list[Filter] = []
    negate = False  # a NOT before the next word or filter
    join = False  # an OR before the next word
    last_open = False  # the last token was a wanted word: an OR may join it
    closed = False  # the last wanted word is a phrase with its closing quote
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        head = _filter_head(text, i)
        if head is None:
            negated = text[i] == "-" and i + 1 < n and not text[i + 1].isspace()
            j = i + 1 if negated else i
            if j < n and text[j] == '"':
                close = text.find('"', j + 1)
                end = n if close < 0 else close
                word, i, phrase, open_quote = text[j + 1 : end], min(n, end + 1), True, close < 0
            else:
                end = j
                while end < n and not text[end].isspace():
                    end += 1
                word, i, phrase, open_quote = text[j:end].strip('"'), end, False, False
                if not negated and word in _OPERATORS:
                    negate = negate or word == "NOT"
                    join = word == "OR" and last_open
                    continue
            negated = negated or negate
            negate = False
            starred = not phrase and word.endswith("*")
            word = word.rstrip("*") if starred else word
            if not any(c.isalnum() for c in word):  # punctuation alone searches nothing
                join = last_open = False
                continue
            if negated:
                excluded.append(Term(word, phrase, starred))
                join = last_open = False
                continue
            term = Term(word, phrase, starred)
            closed = phrase and not open_quote
            if join and clauses:
                clauses[-1].append(term)
            else:
                clauses.append([term])
            join, last_open = False, True
            continue
        negated, name, j = head
        if j < n and text[j] == '"':
            close = text.find('"', j + 1)
            end = n if close < 0 else close
            value, i, quoted = text[j + 1 : end], min(n, end + 1), True
        else:
            end = j
            while end < n and not text[end].isspace():
                end += 1
            value, i, quoted = text[j:end], end, False
        value, any_of = _filter_value(name, value, quoted)
        filters.append(Filter(name, value, negated or negate, any_of))
        negate = join = False  # filters do not take part in OR; ``a tag:x OR b`` is fine
    if clauses and not closed:  # the last word is still being typed (filters go after it)
        last = clauses[-1][-1]
        clauses[-1][-1] = Term(last.text, last.phrase, prefix=True)
    return ParsedQuery(clauses, excluded, filters)


def format_filter(f: Filter) -> str:
    """The filter as it is typed: quoted when the value has spaces or quotes, or a comma
    that is part of it rather than a list."""
    value = f.value
    if not value or any(c.isspace() or c == '"' or (c == "," and not f.any_of) for c in value):
        value = '"' + value.replace('"', "") + '"'
    return f"{'-' if f.negated else ''}{f.name}:{value}"
