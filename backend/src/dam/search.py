"""Full-text search over the ``file_fts`` index."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import Engine, text

from dam.core.paths import nfc


@dataclass
class SearchHit:
    drive_id: str
    path: str
    name: str
    snippet: str
    rank: float


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


def search(
    engine: Engine, query: str, limit: int = 50, folder: str | None = None
) -> list[SearchHit]:
    """Best matches first. Skips missing and parked files; ``folder`` limits to a subtree."""
    match = _fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT f.drive_id, f.path, f.name, "
        "snippet(file_fts, 3, :open, :close, '…', 12) AS snip, bm25(file_fts) AS rank "
        "FROM file_fts JOIN files f ON f.drive_id = file_fts.drive_id "
        "WHERE file_fts MATCH :q AND f.missing IS NOT 1 AND f.parked_at IS NULL"
    )
    params: dict = {"q": match, "limit": limit, "open": _OPEN, "close": _CLOSE}
    base = nfc(folder).strip("/") if folder else ""
    if base:
        sql += " AND (f.path_nfc = :folder OR f.path_nfc LIKE :pattern ESCAPE '\\')"
        params["folder"] = base
        params["pattern"] = _like_escape(base) + "/%"
    sql += " ORDER BY rank, f.path LIMIT :limit"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    return [SearchHit(r.drive_id, r.path, r.name, _snippet(r.snip, r.name), r.rank) for r in rows]


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
