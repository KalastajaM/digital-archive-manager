"""Full-text search over the ``file_fts`` index."""

import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, select, text

from dam import packs
from dam.core.paths import nfc
from dam.core.text import fold
from dam.db.tables import collection_members, collections, file_assignments, files, tags
from dam.query import Filter, date_span, extensions_of, parse_query


@dataclass
class SearchHit:
    drive_id: str
    path: str
    name: str
    snippet: str
    rank: float
    size: int | None = None
    mtime: float | None = None


# Private markers so a literal "[" in the body is never mistaken for a match.
_OPEN, _CLOSE = "\x02", "\x03"
# whitespace and control characters, collapsed to one space in snippets
_CONTROLS = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")
# Removed outright (they sit inside words): soft hyphens, zero-width characters and Unicode
# noncharacters such as U+FFFE, which PDF extraction leaves where a word was hyphenated.
_INVISIBLE = re.compile("[\u00ad\u200b-\u200d\u2060\ufeff\ufdd0-\ufdef\ufffe\uffff]")


def _fts_query(query: str) -> str:
    """Quote every whitespace token (FTS5 syntax chars become literals); prefix-match the last."""
    cleaned = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in nfc(query))
    words = [w for w in cleaned.split() if any(c.isalnum() for c in w)]
    tokens = ['"' + w.replace('"', '""') + '"' for w in words]
    if not tokens:
        return ""
    tokens[-1] += "*"
    return " ".join(tokens)


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tag_ids(
    engine: Engine, names: list[str], skip_unknown: bool = False
) -> list[list[int]] | None:
    """For each wanted tag the ids of the tags with that name (case and accents ignored);
    None when one of them does not exist, so nothing can match (or, with
    ``skip_unknown``, when none of them exists)."""
    with engine.connect() as conn:
        known = [(r.id, fold(r.name)) for r in conn.execute(select(tags.c.id, tags.c.name))]
    found: list[list[int]] = []
    for name in dict.fromkeys(n.strip() for n in names if n.strip()):
        ids = [i for i, folded in known if folded == fold(name)]
        if ids:
            found.append(ids)
        elif not skip_unknown:
            return None
    return found if found or not skip_unknown else None


@dataclass
class SearchContext:
    """What the filters need that the index tables do not say."""

    # ``(tray id, tray name)`` of every configured tray, for ``tray:``
    trays: Callable[[], list[tuple[str, str]]] = list
    # the labels of the extra folders that are not connected now, for ``is:disconnected``
    disconnected: tuple[str, ...] = ()


class _Where:
    """The AND-ed conditions of a search, with their numbered parameters."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.params: dict = {}
        self._n = 0

    def bind(self, value: object) -> str:
        """A fresh parameter holding ``value``: its ``:name``."""
        self._n += 1
        key = f"w{self._n}"
        self.params[key] = value
        return f":{key}"

    def marks(self, values: list) -> str:
        return ", ".join(self.bind(v) for v in values)

    def add(self, sql: str, negated: bool = False) -> None:
        self.parts.append(f"NOT COALESCE(({sql}), 0)" if negated else f"({sql})")


def _wildcards(value: str) -> str:
    """A ``name:`` pattern as LIKE text: ``*`` is any run, ``?`` one character."""
    return "".join("%" if c == "*" else "_" if c == "?" else _like_escape(c) for c in value)


def _under_any(w: _Where, paths: list[str]) -> str:
    """SQL for "is, or lies under, one of these folders" (ASCII case ignored)."""
    bits = []
    for p in paths:
        base = _like_escape(nfc(p).strip("/"))
        bits.append(f"f.path_nfc LIKE {w.bind(base)} ESCAPE '\\'")
        bits.append(f"f.path_nfc LIKE {w.bind(base + '/%')} ESCAPE '\\'")
    return " OR ".join(bits) if bits else "0"


def _member_cond(engine: Engine, w: _Where, collection_ids: list[int]) -> str:
    """Files that are members of these collections, or lie under a member folder."""
    if not collection_ids:
        return "0"
    sql = (
        "f.drive_id IN (SELECT drive_id FROM collection_members "
        f"WHERE collection_id IN ({w.marks(collection_ids)}))"
    )
    with engine.connect() as conn:
        folders = conn.execute(
            select(files.c.path_nfc)
            .select_from(
                collection_members.join(files, files.c.drive_id == collection_members.c.drive_id)
            )
            .where(collection_members.c.collection_id.in_(collection_ids), files.c.is_dir.is_(True))
        ).scalars()
        folder_paths = list(folders)
    if folder_paths:
        sql += " OR " + _under_any(w, folder_paths)
    return sql


def _collection_ids(engine: Engine, value: str) -> list[int]:
    """The ordinary collection called ``value`` (case ignored) and every collection below it."""
    want = nfc(value).strip().casefold()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                collections.c.id,
                collections.c.name_fold,
                collections.c.parent_id,
                collections.c.kind,
            )
        ).all()
    children: dict[int, list[int]] = {}
    for r in rows:
        if r.parent_id is not None:
            children.setdefault(r.parent_id, []).append(r.id)
    todo = [r.id for r in rows if r.kind is None and r.name_fold == want]
    found: list[int] = []
    while todo:
        cid = todo.pop()
        if cid not in found:
            found.append(cid)
            todo.extend(children.get(cid, []))
    return found


def _builtin_id(engine: Engine, kind: str) -> list[int]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(collections.c.id).where(collections.c.kind == kind)).scalars()
        )


def _assigned(engine: Engine, column: str, value: str) -> list[str]:
    """The distinct From / For values that contain ``value`` (case and accents ignored)."""
    col = file_assignments.c[column]
    with engine.connect() as conn:
        names = conn.execute(select(col).where(col.is_not(None)).distinct()).scalars()
        want = fold(value)
        return [n for n in names if want in fold(n)]


def _trays_matching(ctx: SearchContext, value: str) -> list[str]:
    """Tray ids whose id or name is ``value`` (case and accents ignored); the value itself
    when no tray of that name is configured (items of a removed tray keep its id)."""
    want = fold(value.strip())
    ids = [tid for tid, name in ctx.trays() if fold(tid) == want or fold(name) == want]
    return ids or [value.strip()]


def _local_epoch(day: date) -> float:
    return datetime(day.year, day.month, day.day).timestamp()  # the machine's time zone


def _id_keys(value: str) -> list[str]:
    """``value`` without spaces, dashes or case, as stored values are compared; the VAT
    form of a Finnish business ID (FI01120389) also as its eight digits."""
    compact = re.sub(r"[\s-]", "", value).upper()
    vat = re.fullmatch(r"FI(\d{8})", compact)
    return [compact, vat[1]] if vat else [compact]


def _add_filter(engine: Engine, w: _Where, f: Filter, ctx: SearchContext) -> None:
    neg = f.negated
    v = f.value
    if f.name == "name":
        if not any(c in v for c in "*?"):
            v = f"*{v}*"  # no wildcard: the text anywhere in the name
        forms = list(dict.fromkeys([nfc(v), unicodedata.normalize("NFD", v)]))
        w.add(" OR ".join(f"f.name LIKE {w.bind(_wildcards(x))} ESCAPE '\\'" for x in forms), neg)
    elif f.name == "in":
        w.add(_under_any(w, [v]), neg)
    elif f.name == "collection":
        w.add(_member_cond(engine, w, _collection_ids(engine, v)), neg)
    elif f.name in ("from", "for"):
        column = "sender" if f.name == "from" else "person"
        names = _assigned(engine, column, v)
        w.add(
            f"f.drive_id IN (SELECT drive_id FROM file_assignments WHERE {column} IN "
            f"({w.marks(names)}))"
            if names
            else "0",
            neg,
        )
    elif f.name == "id":
        # business IDs, IBANs and domains of the enabled packs, compared without spaces,
        # dashes or case; the current content's only
        kinds = [s.kind for p in packs.active().countries for s in p.identifiers]
        w.add(
            "f.drive_id IN (SELECT i.drive_id FROM file_identifiers i JOIN files x "
            "ON x.drive_id = i.drive_id AND x.sha256 = i.sha256 "
            f"WHERE i.kind IN ({w.marks(kinds)}) AND "
            "REPLACE(REPLACE(UPPER(i.value), ' ', ''), '-', '') "
            f"IN ({w.marks(_id_keys(v))}))",
            neg,
        )
    elif f.name == "type":
        w.add(f"COALESCE(f.ext, '') IN ({w.marks(list(extensions_of(v)))})", neg)
    elif f.name in ("date", "before", "after"):
        first, after = date_span(v)
        # date: the whole period; after: from its first day on; before: up to its first day
        lo, hi = (
            (first, after)
            if f.name == "date"
            else (first, None)
            if f.name == "after"
            else (None, first)
        )
        # the document date; a file without one is dated by the modified time Browse shows
        day, mtime = [], []
        if lo is not None:
            day.append(f"f.doc_date >= {w.bind(lo.isoformat())}")
            mtime.append(f"f.mtime >= {w.bind(_local_epoch(lo))}")
        if hi is not None:
            day.append(f"f.doc_date < {w.bind(hi.isoformat())}")
            mtime.append(f"f.mtime < {w.bind(_local_epoch(hi))}")
        w.add(
            f"({' AND '.join(day)}) OR (f.doc_date IS NULL AND {' AND '.join(mtime)})",
            neg,
        )
    elif f.name == "tray":
        marks = w.marks(_trays_matching(ctx, v))
        w.add(
            "f.drive_id IN (SELECT x.drive_id FROM item_files x JOIN items i ON i.id = x.item_id "
            f"WHERE i.state = 'open' AND i.tray_id IN ({marks}))",
            neg,
        )
    elif f.name == "is":
        _add_is(engine, w, v, neg, ctx)
    # ``tag`` is handled with the tag mode by the caller


def _add_is(engine: Engine, w: _Where, value: str, neg: bool, ctx: SearchContext) -> None:
    if value == "starred":
        w.add(_member_cond(engine, w, _builtin_id(engine, "starred")), neg)
    elif value == "important":
        w.add(_member_cond(engine, w, _builtin_id(engine, "important")), neg)
    elif value == "locked":
        # the owner's own locks only; Important files are found with is:important
        w.add("f.drive_id IN (SELECT drive_id FROM file_locks)", neg)
    elif value == "todo":
        w.add(
            "f.drive_id IN (SELECT target_id FROM checklist_items "
            "WHERE target_kind = 'file' AND done = 0) OR f.drive_id IN ("
            "SELECT x.drive_id FROM item_files x JOIN items i ON i.id = x.item_id "
            "WHERE i.state = 'open' AND CAST(i.id AS TEXT) IN ("
            "SELECT target_id FROM checklist_items WHERE target_kind = 'item' AND done = 0))",
            neg,
        )
    elif value == "note":
        w.add(
            "f.drive_id IN (SELECT target_id FROM notes "
            "WHERE target_kind = 'file' AND TRIM(text) != '')",
            neg,
        )
    elif value == "summary":
        w.add("f.drive_id IN (SELECT drive_id FROM file_summaries WHERE TRIM(summary) != '')", neg)
    elif value == "disconnected":
        w.add(_under_any(w, list(ctx.disconnected)), neg)  # none: "0", nothing found


def search(
    engine: Engine,
    query: str,
    limit: int = 50,
    folder: str | None = None,
    tag_names: list[str] | None = None,
    tag_mode: str = "all",
    ctx: SearchContext | None = None,
) -> list[SearchHit]:
    """Best matches first. Skips missing and parked files; ``folder`` limits to a subtree.

    ``query`` is plain words and ``name:value`` filters (``dam.query``). Every filter must
    hold; a ``-`` filter excludes. ``tag_names`` are more ``tag:`` filters: files with every
    one of the tags (``tag_mode`` "all") or at least one ("any", for the positive tags;
    a tag that does not exist is then simply left out, all unknown: no hits). Tags are
    looked up in the ``file_tags`` index, so the number of files does not matter. With no
    words the matching files are listed by name. ``QueryError``: a filter value that
    cannot be right."""
    ctx = ctx or SearchContext()
    parsed = parse_query(query)
    match = _fts_query(parsed.words)
    any_mode = tag_mode == "any"
    positive = [f.value for f in parsed.filters if f.name == "tag" and not f.negated]
    positive += list(tag_names or [])
    negative = [f.value for f in parsed.filters if f.name == "tag" and f.negated]
    others = [f for f in parsed.filters if f.name != "tag"]
    wanted = _tag_ids(engine, positive, skip_unknown=any_mode) if positive else []
    if wanted is None or (not match and not wanted and not negative and not others):
        return []
    w = _Where()
    params: dict = {"limit": limit, "open": _OPEN, "close": _CLOSE}
    if match:
        sql = (
            "SELECT f.drive_id, f.path, f.name, f.size, f.mtime, "
            "snippet(file_fts, 3, :open, :close, '…', 12) AS snip, bm25(file_fts) AS rank "
            "FROM file_fts JOIN files f ON f.drive_id = file_fts.drive_id "
            "WHERE file_fts MATCH :q AND f.missing IS NOT 1 AND f.parked_at IS NULL"
        )
        params["q"] = match
        order = " ORDER BY rank, f.path LIMIT :limit"
    else:
        sql = (
            "SELECT f.drive_id, f.path, f.name, f.size, f.mtime, NULL AS snip, 0.0 AS rank "
            "FROM files f WHERE f.missing IS NOT 1 AND f.parked_at IS NULL "
            "AND f.is_dir IS NOT 1 AND f.is_link IS NOT 1"
        )
        order = " ORDER BY f.name COLLATE NOCASE, f.path LIMIT :limit"
    if any_mode and wanted:
        # one index lookup over the union of all the ids
        every = [tag_id for ids in wanted for tag_id in ids]
        w.add(f"f.drive_id IN (SELECT drive_id FROM file_tags WHERE tag_id IN ({w.marks(every)}))")
    else:
        for ids in wanted:
            w.add(
                f"f.drive_id IN (SELECT drive_id FROM file_tags WHERE tag_id IN ({w.marks(ids)}))"
            )
    if negative:
        known = _tag_ids(engine, negative, skip_unknown=True)
        every = [tag_id for ids in known or [] for tag_id in ids]
        if every:
            marks = w.marks(every)
            w.add(
                f"f.drive_id IN (SELECT drive_id FROM file_tags WHERE tag_id IN ({marks}))",
                negated=True,
            )
    for f in others:
        _add_filter(engine, w, f, ctx)
    base = nfc(folder).strip("/") if folder else ""
    if base:
        w.parts.append(f"({_under_any(w, [base])})")
    for part in w.parts:
        sql += f" AND {part}"
    params.update(w.params)
    sql += order
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    return [
        SearchHit(r.drive_id, r.path, r.name, _snippet(r.snip, r.name), r.rank, r.size, r.mtime)
        for r in rows
    ]


def _snippet(snip: str | None, name: str) -> str:
    """Bracket the match; a name-only hit (no match in the text) shows the name."""
    if not snip or _OPEN not in snip:
        return name
    text = _INVISIBLE.sub("", snip.replace(_OPEN, "[").replace(_CLOSE, "]"))
    return _CONTROLS.sub(" ", text).strip()


@dataclass
class Candidate:
    drive_id: str
    path: str
    name: str
    rank: float


def _ascii_lower(value: str) -> str:
    """Lower-case the way SQLite's ``lower()`` does: ASCII letters only."""
    return "".join(c.lower() if c.isascii() else c for c in value)


def ranked(engine: Engine, match: str, exclude_folders: list[str]) -> Iterator[Candidate]:
    """Files matching the FTS5 expression ``match``, lazily, best first: hits in the
    text before hits only in the name or path, each by bm25. Live,
    not parked, not folders or links. Files at or under ``exclude_folders`` are left
    out in SQL as far as SQLite can fold (ASCII case); the caller must still check
    every candidate with ``guard.is_excluded`` (NFC and full casefold)."""
    if not match:
        return
    sql = (
        # bm25 over the text column alone (weights drive_id, name, path, text): 0 for a
        # file found only by its name or path, negative (better) for a text hit
        "SELECT f.drive_id, f.path, f.name, bm25(file_fts) AS rank, "
        "bm25(file_fts, 0.0, 0.0, 0.0, 1.0) AS text_rank "
        "FROM file_fts JOIN files f ON f.drive_id = file_fts.drive_id "
        "WHERE file_fts MATCH :q AND f.missing IS NOT 1 AND f.parked_at IS NULL "
        "AND f.is_dir IS NOT 1 AND f.is_link IS NOT 1"
    )
    params: dict = {"q": match}
    for i, folder in enumerate(exclude_folders):
        base = _ascii_lower(nfc(folder).strip().strip("/"))
        if not base:
            continue
        sql += f" AND NOT (lower(f.path_nfc) = :x{i} OR lower(f.path_nfc) LIKE :p{i} ESCAPE '\\')"
        params[f"x{i}"] = base
        params[f"p{i}"] = _like_escape(base) + "/%"
    sql += " ORDER BY CASE WHEN text_rank < 0 THEN 0 ELSE 1 END, rank, f.path"
    with engine.connect() as conn:
        for r in conn.execute(text(sql), params):
            yield Candidate(r.drive_id, r.path, r.name, r.rank)
