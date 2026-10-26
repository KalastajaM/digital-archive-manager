"""A file that gets a new id keeps everything the owner gave it."""

import xattr
from sqlalchemy import insert, select

from dam.db.tables import (
    checklist_items,
    collection_members,
    collections,
    file_assignments,
    file_fields,
    file_locks,
    file_summaries,
    item_files,
    items,
    member_link_names,
    notes,
    rule_outcomes,
)
from dam.index.driveid import DRIVE_ID_XATTR
from dam.index.repo import FileRepo
from dam.index.scanner import scan
from test_repo import rec
from test_scanner import setup

# table -> its column naming the file
_BY_FILE = {
    notes: notes.c.target_id,
    checklist_items: checklist_items.c.target_id,
    collection_members: collection_members.c.drive_id,
    member_link_names: member_link_names.c.drive_id,
    item_files: item_files.c.drive_id,
    file_locks: file_locks.c.drive_id,
    file_assignments: file_assignments.c.drive_id,
    file_summaries: file_summaries.c.drive_id,
    file_fields: file_fields.c.drive_id,
    rule_outcomes: rule_outcomes.c.drive_id,
}


def _attach_everything(engine, drive_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(collections).values(id=901, name="Car zz", name_fold="car zz", created=1.0)
        )
        conn.execute(
            insert(items).values(id=901, tray_id="bills", title="t", fields={}, created=1.0)
        )
        conn.execute(
            insert(notes).values(target_kind="file", target_id=drive_id, text="n", updated=1.0)
        )
        conn.execute(
            insert(checklist_items).values(
                target_kind="file", target_id=drive_id, text="c", position=0
            )
        )
        conn.execute(
            insert(collection_members).values(collection_id=901, drive_id=drive_id, added=1)
        )
        conn.execute(
            insert(member_link_names).values(collection_id=901, drive_id=drive_id, link_name="x")
        )
        conn.execute(insert(item_files).values(item_id=901, drive_id=drive_id))
        conn.execute(insert(file_locks).values(drive_id=drive_id, locked_at=1.0))
        conn.execute(insert(file_assignments).values(drive_id=drive_id, set_by="owner", set_at=1.0))
        conn.execute(
            insert(file_summaries).values(
                drive_id=drive_id, source="text", summary="s", key_facts=[], at=1.0
            )
        )
        conn.execute(insert(file_fields).values(drive_id=drive_id, fields="{}", updated=1.0))
        conn.execute(
            insert(rule_outcomes).values(
                batch_id="b", drive_id=drive_id, rule_id="r", field="folder", kept=True, created=1
            )
        )


def _ids(engine) -> dict[str, set[str]]:
    with engine.connect() as conn:
        return {t.name: set(conn.execute(select(col)).scalars()) for t, col in _BY_FILE.items()}


def test_rekey_keeps_notes_collections_items_locks(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("local:a", "a.pdf"))
    _attach_everything(engine, "local:a")
    repo.rekey("local:a", "drv-1")
    assert _ids(engine) == {t.name: {"drv-1"} for t in _BY_FILE}


def test_rekey_leaves_notes_of_other_kinds(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("local:a", "a.pdf"))
    with engine.begin() as conn:  # an item note whose id happens to look the same
        conn.execute(
            insert(notes).values(target_kind="item", target_id="local:a", text="n", updated=1.0)
        )
    repo.rekey("local:a", "drv-1")
    with engine.connect() as conn:
        assert conn.execute(select(notes.c.target_id)).scalar_one() == "local:a"


def test_scanner_rekey_keeps_note(fake_archive, engine):
    path = fake_archive.add("##. Organize/a.pdf", drive_id=None)
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    local = repo.by_path("##. Organize/a.pdf").drive_id
    _attach_everything(engine, local)
    xattr.setxattr(path, DRIVE_ID_XATTR, b"drv-9")
    scan(paths, repo)
    assert _ids(engine) == {t.name: {"drv-9"} for t in _BY_FILE}
