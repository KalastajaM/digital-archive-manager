"""Folder suggestions learned from the archive: where do already-filed files that look
like this document live? Plain code over the FTS index, no AI.

The file's name and the start of its text (where the sender or company usually is) give
a few distinctive words; the best-matching filed files vote for their folder. A folder
is only suggested when at least ``MIN_VOTES`` of the top matches are in it and it holds
at least ``MIN_SHARE`` of them."""

import re
from collections import Counter
from pathlib import PurePosixPath

from sqlalchemy import Engine, text

from dam.core.naming import fix_mojibake
from dam.core.paths import nfc

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


def _tokens(stem: str, body: str) -> list[str]:
    out: list[str] = []
    for source in (stem, body[:TEXT_CHARS]):
        for w in _WORD.findall(nfc(source)):
            w = w.casefold()
            if w not in _STOP and w not in out:
                out.append(w)
    return out[:MAX_TOKENS]


def _special(path: str) -> bool:
    return any(part.startswith("##.") for part in PurePosixPath(nfc(path)).parts)


def similar_folder(
    engine: Engine, drive_id: str, name: str, body: str, ext: str | None = None
) -> str | None:
    """The folder most of the best-matching filed files are in, or None when nothing
    matches well enough. One indexed FTS query."""
    stem = fix_mojibake(name)
    if ext and stem.lower().endswith("." + ext.lower()):
        stem = stem[: -len(ext) - 1]
    words = _tokens(stem, body)
    if not words:
        return None
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
        if _special(r.path):
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
