"""Where the file a journal op names is now, from the index, for Activity's "Show in
Browse". The journal keeps the paths as they were; since then the file may have been
moved on, marked for deletion or deleted by hand. Read-only."""

from collections.abc import Callable, Iterable

from dam.core.paths import nfc
from dam.index.repo import FileRecord, FileRepo
from dam.ops.undo import ACTED

# The ops that name a file (or folder) the owner may want to open. A made or removed
# folder and a removed link name nothing that is still there to show.
_NAMES_A_FILE = ("move", "rename", "quarantine", "symlink")
_RECONNECT_HOPS = 10  # a file reconnected again and again; more would be a cycle


def op_path(op: dict) -> str | None:
    """Where the op left its file: the destination once it acted, else (planned, failed,
    undone) the source; a link op's file is its target (``src``)."""
    if op["kind"] == "symlink":
        return op["src"]
    return op["dst"] if op["state"] in ACTED else op["src"]


def files_now(
    repo: FileRepo, is_quarantined: Callable[[str], bool], ops: Iterable[dict]
) -> list[dict | None]:
    """For each op (journal rows as dicts), its file now: ``state`` is ``here`` (where the
    op left it), ``moved`` (elsewhere), ``to_delete`` (since marked for deletion) or
    ``missing`` (deleted, or moved outside dam and not reconnected), with the current
    ``path`` and ``drive_id`` (None when missing) and ``is_dir``. None for an op that
    names no file. Found by the op's id (following reconnects), else by its path."""
    ops = list(ops)
    names = [op["kind"] in _NAMES_A_FILE and bool(op_path(op)) for op in ops]
    wanted = [op for op, named in zip(ops, names, strict=True) if named]
    by_id = repo.get_many({op["drive_id"] for op in wanted if op["drive_id"]})
    by_path = repo.live_by_paths({op_path(op) for op in wanted if not op["drive_id"]})
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
        rec = (
            _follow(op["drive_id"], by_id, moved_to)
            if op["drive_id"]
            else by_path.get(nfc(op_path(op)))
        )
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
    is_dir = op["is_file"] is False if rec is None else rec.is_dir
    if rec is None:
        return {"state": "missing", "path": None, "drive_id": None, "is_dir": is_dir}
    if rec.path_nfc == nfc(op_path(op)):
        state = "here"
    elif is_quarantined(rec.path_nfc):
        state = "to_delete"
    else:
        state = "moved"
    return {"state": state, "path": rec.path, "drive_id": rec.drive_id, "is_dir": is_dir}
