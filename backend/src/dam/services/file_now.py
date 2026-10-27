"""Where the file or folder a journal op names is now, from the index, for Activity's
"Show in Browse". The journal keeps the paths as they were; since then the file may have
been moved on, marked for deletion or deleted by hand. A folder has no stable id in the
journal, so it is followed by path through the later moves, renames and moves to To Delete
of it or of a folder above it. Read-only."""

from collections.abc import Callable, Iterable

from sqlalchemy import Engine, or_, select

from dam.core.paths import nfc
from dam.db.tables import operations
from dam.index.repo import FileRecord, FileRepo
from dam.ops.guards import is_under, rebase
from dam.ops.undo import ACTED

# The ops that name a file or folder the owner may want to open (a folder: a folder
# moved, renamed, made, or moved to To Delete). A removed folder and a removed link name
# nothing that is still there to show.
_NAMES_A_FILE = ("move", "rename", "quarantine", "symlink", "mkdir")
_RELOCATES = ("move", "rename", "quarantine")  # the ops that change where a folder is
_RECONNECT_HOPS = 10  # a file reconnected again and again; more would be a cycle


def op_path(op: dict) -> str | None:
    """Where the op left its file: the destination once it acted, else (planned, failed,
    undone) the source; a link op's file is its target (``src``)."""
    if op["kind"] == "symlink":
        return op["src"]
    if op["state"] not in ACTED:
        return op["src"]
    # a folder moved across disks: its subject is the copy, not the original in To Delete
    return op.get("copied_to") or op["dst"]


def _is_folder(op: dict) -> bool:
    return op["kind"] == "mkdir" or op["is_file"] is False


def later_relocations(engine: Engine) -> Callable[[int], list[dict]]:
    """``files_now``'s ``later``: the folder-sized relocations (move, rename, move to To
    Delete, that acted) with a journal id above the given one, oldest first."""

    def fetch(after: int) -> list[dict]:
        o = operations.c
        with engine.connect() as conn:
            rows = conn.execute(
                select(o.id, o.src, o.dst, o.copied_to)
                .where(
                    o.id > after,
                    o.kind.in_(_RELOCATES),
                    o.state.in_(ACTED),
                    or_(o.is_file.is_(None), o.is_file.is_(False)),
                )
                .order_by(o.id)
            )
            return [dict(r) for r in rows.mappings()]

    return fetch


def _follow_folder(op: dict, later: list[dict]) -> str:
    """The folder the op names, carried through every later relocation of it or of a
    folder above it, to where it should be now."""
    path = op_path(op)
    for row in later:
        if row["id"] > op["id"] and row["src"] and is_under(path, row["src"]):
            target = row["copied_to"] or row["dst"]
            if target:
                path = rebase(path, row["src"], target)
    return path


def files_now(
    repo: FileRepo,
    is_quarantined: Callable[[str], bool],
    ops: Iterable[dict],
    later: Callable[[int], list[dict]] | None = None,
) -> list[dict | None]:
    """For each op (journal rows as dicts), its file now: ``state`` is ``here`` (where the
    op left it), ``moved`` (elsewhere), ``to_delete`` (since marked for deletion) or
    ``missing`` (deleted, or moved outside dam and not reconnected), with the current
    ``path`` and ``drive_id`` (None when missing) and ``is_dir``. None for an op that
    names no file. Found by the op's id (following reconnects), else by its path. A
    folder is also looked for by path when its id finds nothing, at the place the later
    relocations in ``later`` (``later_relocations``; none: the op's own path) carried it."""
    ops = list(ops)
    names = [op["kind"] in _NAMES_A_FILE and bool(op_path(op)) for op in ops]
    wanted = [op for op, named in zip(ops, names, strict=True) if named]
    folders = [op for op in wanted if _is_folder(op)]
    moves = later(min(op["id"] for op in folders)) if later and folders else []
    where = {id(op): _follow_folder(op, moves) if _is_folder(op) else op_path(op) for op in wanted}
    by_id = repo.get_many({op["drive_id"] for op in wanted if op["drive_id"]})
    by_path = repo.live_by_paths(
        {where[id(op)] for op in wanted if not op["drive_id"] or _is_folder(op)}
    )
    # ids whose row is gone or missing: perhaps reconnected to a file found elsewhere
    lost = {
        op["drive_id"] for op in wanted if op["drive_id"] and not _live(by_id.get(op["drive_id"]))
    }
    moved_to: dict[str, str] = {}
    for _ in range(_RECONNECT_HOPS):
        step = repo.reconnected_to(lost)
        if not step:
            break
        moved_to.update(step)
        by_id.update(repo.get_many(set(step.values()) - by_id.keys()))
        lost = {new for new in step.values() if not _live(by_id.get(new))}
    out: list[dict | None] = []
    for op, named in zip(ops, names, strict=True):
        if not named:
            out.append(None)
            continue
        rec = _follow(op["drive_id"], by_id, moved_to) if op["drive_id"] else None
        if rec is None and (not op["drive_id"] or _is_folder(op)):
            rec = by_path.get(nfc(where[id(op)]))
        out.append(_where(op, rec, is_quarantined))
    return out


def _live(rec: FileRecord | None) -> bool:
    return rec is not None and not rec.missing and rec.parked_at is None


def _follow(
    drive_id: str, by_id: dict[str, FileRecord], moved_to: dict[str, str]
) -> FileRecord | None:
    for _ in range(_RECONNECT_HOPS + 1):
        rec = by_id.get(drive_id)
        if _live(rec):
            return rec
        if drive_id not in moved_to:
            return None
        drive_id = moved_to[drive_id]
    return None


def _where(op: dict, rec: FileRecord | None, is_quarantined: Callable[[str], bool]) -> dict:
    is_dir = _is_folder(op) if rec is None else rec.is_dir
    if rec is None:
        return {"state": "missing", "path": None, "drive_id": None, "is_dir": is_dir}
    if rec.path_nfc == nfc(op_path(op)):
        state = "here"
    elif is_quarantined(rec.path_nfc):
        state = "to_delete"
    else:
        state = "moved"
    return {"state": state, "path": rec.path, "drive_id": rec.drive_id, "is_dir": is_dir}
