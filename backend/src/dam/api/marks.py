"""``marks`` on the file records the API returns: one ``MarkService.marks_for`` query per
response, whatever the number of rows (never a query per row). The same helpers set
``folder`` and ``connected`` (``_place``), with one look at the extra folders per
response."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from dam.app import App


def _dict(obj: Any) -> dict:
    return asdict(obj) if is_dataclass(obj) else dict(obj)


def _place(app: App, rows: Iterable[dict]) -> None:
    """Set ``folder`` (the extra folder's label, None for the main folder) and
    ``connected`` on every record dict that has a ``path``; others are left as they are."""
    offline = set(app.paths.disconnected_labels())
    for r in rows:
        path = r.get("path")
        if not isinstance(path, str):
            continue
        folder = app.paths.label_of(path) or None
        r["folder"] = folder
        r["connected"] = folder not in offline


def with_marks(app: App, rows: Iterable[Any], key: str = "drive_id") -> list[dict]:
    """``rows`` (dataclasses or dicts) as dicts, each with its ``marks``, ``folder``
    and ``connected``."""
    out = [_dict(r) for r in rows]
    _place(app, out)
    found = app.marks.marks_for([r[key] for r in out])
    for r in out:
        r["marks"] = found.get(r[key], [])
    return out


def with_record_marks(app: App, rows: Iterable[Any]) -> list[dict]:
    """``rows`` holding a file ``record`` (inbox entries, file detail) as dicts, the
    record with its ``marks``, ``folder`` and ``connected``."""
    out = [_dict(r) for r in rows]
    _place(app, [r["record"] for r in out])
    found = app.marks.marks_for([r["record"]["drive_id"] for r in out])
    for r in out:
        r["record"]["marks"] = found.get(r["record"]["drive_id"], [])
    return out


def collections_out(app: App, cols: Iterable[Any], extra: list[dict] | None = None) -> list[dict]:
    """Collections as dicts, each member with its ``marks`` (one query for all of
    them), and ``folder`` / ``connected`` when it has a path. ``extra``: fields to merge
    into each, in the same order."""
    out = [_dict(c) for c in cols]
    if extra is not None:
        for c, more in zip(out, extra, strict=True):
            c.update(more)
    _place(app, [m for c in out for m in c["members"]])
    found = app.marks.marks_for([m["drive_id"] for c in out for m in c["members"]])
    for c in out:
        for m in c["members"]:
            m["marks"] = found.get(m["drive_id"], [])
    return out


def collection_out(app: App, c: Any) -> dict:
    return collections_out(app, [c])[0]


def entries_out(app: App, entries: Iterable[Any]) -> list[dict]:
    """Convert-screen entries (``##. Ongoing`` / ``##. Important``) as dicts, each entry
    and each of its items with the marks of the file it stands for (one query)."""
    out = [_dict(e) for e in entries]
    ids = [e["drive_id"] for e in out if e["drive_id"]]
    ids += [i["drive_id"] for e in out for i in e["items"] if i["drive_id"]]
    found = app.marks.marks_for(ids) if ids else {}
    for e in out:
        e["marks"] = found.get(e["drive_id"], []) if e["drive_id"] else []
        for i in e["items"]:
            i["marks"] = found.get(i["drive_id"], []) if i["drive_id"] else []
    return out


def journal_out(app: App, rows: Iterable[Any]) -> list[dict]:
    """Journal rows as dicts, each with the marks of the file it names (one query)."""
    out = [_dict(r) for r in rows]
    ids = [r["drive_id"] for r in out if r["drive_id"]]
    found = app.marks.marks_for(ids) if ids else {}
    for r in out:
        r["marks"] = found.get(r["drive_id"], []) if r["drive_id"] else []
    return out


def batches_out(app: App, batches: Iterable[Any]) -> list[dict]:
    """Activity batches as dicts, every op with its file's marks (one query in all)."""
    out = [_dict(b) for b in batches]
    ids = [op["drive_id"] for b in out for op in b["ops"] if op["drive_id"]]
    found = app.marks.marks_for(ids) if ids else {}
    for b in out:
        for op in b["ops"]:
            op["marks"] = found.get(op["drive_id"], []) if op["drive_id"] else []
    return out
