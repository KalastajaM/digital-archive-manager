"""Folder suggestions learned from the archive: where do already-filed files that look
like this document live? Plain code over the FTS index, no AI.

The file's name and the start of its text (where the sender or company usually is) give
a few distinctive words; the best-matching filed files vote for their folder. A folder
is only suggested when at least ``MIN_VOTES`` of the top matches are in it and it holds
at least ``MIN_SHARE`` of them."""

import re
import threading
from collections import Counter, OrderedDict
from pathlib import PurePosixPath

from sqlalchemy import Engine, text

from dam.core.naming import fix_mojibake
from dam.core.paths import fold_name, nfc
from dam.db.generation import WriteGeneration

SOURCE = "similar files"
TOP = 10  # best matches that vote
MIN_VOTES = 2
MIN_SHARE = 0.5
MAX_TOKENS = 10
TEXT_CHARS = 400  # of the text searched for words
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
# words that say what kind of document it is or how it was made, not who it is from
_STOP = frozenset(
    "scan scanned document documents image images invoice lasku kuitti receipt letter "
    "kirje page pages copy final draft print this that with from your have been will "
    "oikea sivu liite attachment screenshot".split()
)


def word_tokens(stem: str, body: str) -> list[str]:
    out: list[str] = []
    for source in (stem, body[:TEXT_CHARS]):
        for w in _WORD.findall(nfc(source)):
            w = w.casefold()
            if w not in _STOP and w not in out:
                out.append(w)
    return out[:MAX_TOKENS]


def _special(path: str, names: tuple[str, ...] = ()) -> bool:
    """The path is in one of the app's own folders: any ``##.`` folder, or one of
    ``names`` (the configured names, which need not start with ``##.``)."""
    parts = PurePosixPath(nfc(path)).parts
    if any(part.startswith("##.") for part in parts):
        return True
    return any(fold_name(part) in {fold_name(n) for n in names} for part in parts[:2])


def _words(name: str, body: str, ext: str | None) -> list[str]:
    """The words searched for: from the name (without its extension) and the text."""
    stem = fix_mojibake(name)
    if ext and stem.lower().endswith("." + ext.lower()):
        stem = stem[: -len(ext) - 1]
    return word_tokens(stem, body)


def similar_folder(
    engine: Engine,
    drive_id: str,
    name: str,
    body: str,
    ext: str | None = None,
    special: tuple[str, ...] = (),
) -> str | None:
    """The folder most of the best-matching filed files are in, or None when nothing
    matches well enough. One indexed FTS query."""
    words = _words(name, body, ext)
    return _search(engine, drive_id, words, special) if words else None


class SimilarFolders:
    """``similar_folder`` with the answers kept (the last ``size`` asked) until the index
    changes: any write to the files or the search rows (a file indexed, filed, moved,
    renamed or gone) starts afresh, since any of them can change the vote. The answer
    for one file depends only on its words, so new text gives a new search too."""

    def __init__(self, engine: Engine, size: int = 2048, special: tuple[str, ...] = ()) -> None:
        self._engine = engine
        self._special = special
        self._size = size
        self._generation = WriteGeneration(engine, ("files", "file_fts"))
        self._kept: OrderedDict[tuple[str, tuple[str, ...]], str | None] = OrderedDict()
        self._kept_at = self._generation.value
        self._lock = threading.Lock()

    def folder(self, drive_id: str, name: str, body: str, ext: str | None = None) -> str | None:
        words = _words(name, body, ext)
        if not words:
            return None
        key = (drive_id, tuple(words))
        at = self._generation.value
        with self._lock:
            if self._kept_at != at:
                self._kept.clear()
                self._kept_at = at
            if key in self._kept:
                self._kept.move_to_end(key)
                return self._kept[key]
        found = _search(self._engine, drive_id, words, self._special)
        with self._lock:
            # an index write while searching: the answer may be from the old rows
            if self._generation.value == at == self._kept_at:
                self._kept[key] = found
                if len(self._kept) > self._size:
                    self._kept.popitem(last=False)
        return found


def _search(
    engine: Engine, drive_id: str, words: list[str], special: tuple[str, ...] = ()
) -> str | None:
    match = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
    sql = (
        "SELECT f.path FROM file_fts JOIN files f ON f.drive_id = file_fts.drive_id "
        "WHERE file_fts MATCH :q AND f.drive_id != :id AND f.missing IS NOT 1 "
        "AND f.parked_at IS NULL AND f.is_dir IS NOT 1 AND f.is_link IS NOT 1 "
        "ORDER BY bm25(file_fts, 0.0, 4.0, 1.0, 1.0) LIMIT 60"
    )
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"q": match, "id": drive_id}).all()
    folders: list[str] = []
    for r in rows:
        if _special(r.path, special):
            continue
        parent = PurePosixPath(r.path).parent.as_posix()
        if parent != ".":
            folders.append(parent)
        if len(folders) == TOP:
            break
    if not folders:
        return None
    folder, votes = Counter(folders).most_common(1)[0]
    if votes >= MIN_VOTES and votes / len(folders) >= MIN_SHARE:
        return folder
    return None
