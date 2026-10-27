"""Maintenance, "Moved outside dam": a file without a Drive id that was renamed or moved in
Finder or Explorer gets a new index row, and what the owner gave it stays on the old,
missing one. The check pairs the two by size and content; reconnecting moves everything to
the new row and drops the old one. Database only; fake archives only."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from dam.api import create_api
from dam.db.tables import (
    checklist_items,
    collection_members,
    file_assigned_codes,
    file_assignments,
    file_fields,
    file_locks,
    file_summaries,
    file_tags,
    files,
    item_files,
    member_link_names,
    notes,
    rule_outcomes,
)
from dam.errors import InvalidRequest
from dam.maintenance import duplicates
from dam.search import search

BANKS = "10. Financial/Banks"
HOME = "20. Home"
BASE = "http://127.0.0.1:8765"
H = {"Origin": BASE}


def run(app):
    job = app.maintenance.start("moved")
    job.join(15)
    assert job.view().state == "done", job.view().error
    return app.maintenance.result_of(job)[1]


def local_id(app, rel: str) -> str:
    rec = app.repo.by_path(rel)
    assert rec is not None and rec.drive_id.startswith("local:")
    return rec.drive_id


def index(app) -> None:
    """Scan, then read every pending file's content (stores its sha256 and text)."""
    app.scan()
    while app.content.run_once():
        pass


def rename(fake_archive, src: str, dst: str) -> None:
    to = fake_archive.root / dst
    to.parent.mkdir(parents=True, exist_ok=True)
    (fake_archive.root / src).rename(to)


@pytest.fixture
def moved(app, fake_archive):
    """``a.txt`` had a tag and a collection, then was renamed outside dam (the new row has
    no hash yet: the check reads it)."""
    fake_archive.add(f"{BANKS}/a.txt", b"heating bill march", drive_id=None)
    index(app)
    old = local_id(app, f"{BANKS}/a.txt")
    app.tags.add(old, ["tax"])
    col = app.collections.create("Trip")
    app.collections.add_members(col.id, [old])
    rename(fake_archive, f"{BANKS}/a.txt", f"{HOME}/renamed.txt")
    app.scan()
    new = local_id(app, f"{HOME}/renamed.txt")
    assert app.repo.get(old).missing and app.repo.get(new).sha256 is None
    return old, new, col


def test_an_exact_match_is_found_and_the_new_file_is_hashed_once(app, moved, monkeypatch):
    old, new, _ = moved
    read: list[str] = []
    real = duplicates.hash_file
    monkeypatch.setattr(
        duplicates, "hash_file", lambda p, stopped: read.append(p.name) or real(p, stopped)
    )
    [pair] = run(app).items
    assert (pair.old_id, pair.old_path, pair.new_id, pair.new_path) == (
        old,
        f"{BANKS}/a.txt",
        new,
        f"{HOME}/renamed.txt",
    )
    assert pair.same_ext and not pair.ambiguous
    assert pair.moves == {"tags": 1, "collections": 1}
    assert read == ["renamed.txt"]
    assert app.repo.get(new).sha256 is not None  # stored the way the content pass does
    run(app)
    assert read == ["renamed.txt"]  # not read again


def test_another_size_or_other_content_is_not_a_match(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.txt", b"aaaa", drive_id=None)
    fake_archive.add(f"{BANKS}/b.txt", b"bbbb", drive_id=None)
    index(app)
    for rel in (f"{BANKS}/a.txt", f"{BANKS}/b.txt"):
        app.tags.add(local_id(app, rel), ["x"])
    rename(fake_archive, f"{BANKS}/a.txt", f"{HOME}/a.txt")
    (fake_archive.root / HOME / "a.txt").write_bytes(b"aaaaa")  # another size
    rename(fake_archive, f"{BANKS}/b.txt", f"{HOME}/b.txt")
    (fake_archive.root / HOME / "b.txt").write_bytes(b"cccc")  # same size, other content
    app.scan()
    result = run(app)
    assert (result.items, result.total) == ([], 0)


def test_a_missing_file_with_nothing_given_or_never_read_is_left_out(app, fake_archive):
    fake_archive.add(f"{BANKS}/plain.txt", b"nothing given", drive_id=None)
    index(app)
    fake_archive.add(f"{BANKS}/unread.txt", b"never read", drive_id=None)
    app.scan()  # no content pass: no hash stored
    app.tags.add(local_id(app, f"{BANKS}/unread.txt"), ["x"])
    rename(fake_archive, f"{BANKS}/plain.txt", f"{HOME}/plain.txt")
    rename(fake_archive, f"{BANKS}/unread.txt", f"{HOME}/unread.txt")
    app.scan()
    result = run(app)
    assert result.items == [] and result.unhashed == 1


def test_one_missing_file_matching_two_new_ones_is_ambiguous(app, moved, fake_archive):
    old, new, _ = moved
    fake_archive.add(f"{HOME}/copy.txt", b"heating bill march", drive_id=None)
    app.scan()
    result = run(app)
    assert {(p.old_id, p.new_path, p.ambiguous) for p in result.items} == {
        (old, f"{HOME}/renamed.txt", True),
        (old, f"{HOME}/copy.txt", True),
    }
    with pytest.raises(InvalidRequest, match="more than one"):
        app.maintenance.reconnect([(old, new)])


def test_two_missing_files_matching_one_new_one_are_ambiguous(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.txt", b"twin", drive_id=None)
    fake_archive.add(f"{HOME}/b.txt", b"twin", drive_id=None)
    index(app)
    olds = [local_id(app, f"{BANKS}/a.txt"), local_id(app, f"{HOME}/b.txt")]
    for drive_id in olds:
        app.tags.add(drive_id, ["x"])
    rename(fake_archive, f"{BANKS}/a.txt", f"{HOME}/c.txt")
    (fake_archive.root / HOME / "b.txt").unlink()
    app.scan()
    result = run(app)
    assert sorted(p.old_id for p in result.items) == sorted(olds)
    assert all(p.ambiguous for p in result.items)


def test_a_changed_extension_is_still_a_match_but_said(app, fake_archive):
    fake_archive.add(f"{BANKS}/scan.txt", b"same bytes", drive_id=None)
    index(app)
    app.tags.add(local_id(app, f"{BANKS}/scan.txt"), ["x"])
    rename(fake_archive, f"{BANKS}/scan.txt", f"{HOME}/scan.md")
    app.scan()
    [pair] = run(app).items
    assert not pair.same_ext and not pair.ambiguous


def _give_everything(app, drive_id: str) -> None:
    with app.engine.begin() as conn:
        conn.execute(
            insert(notes).values(target_kind="file", target_id=drive_id, text="n", updated=1.0)
        )
        conn.execute(
            insert(checklist_items).values(
                target_kind="file", target_id=drive_id, text="c", position=0
            )
        )
        conn.execute(insert(file_locks).values(drive_id=drive_id, locked_at=1.0))
        conn.execute(
            insert(file_assignments).values(
                drive_id=drive_id, sender="Pohjola", set_by="owner", set_at=1.0
            )
        )
        conn.execute(
            insert(file_summaries).values(
                drive_id=drive_id, source="user", summary="s", key_facts=[], at=1.0
            )
        )
        conn.execute(insert(file_fields).values(drive_id=drive_id, fields="[]", updated=1.0))
        conn.execute(
            insert(file_assigned_codes).values(drive_id=drive_id, code="A", assigned_at=1.0)
        )
        conn.execute(
            insert(rule_outcomes).values(
                batch_id="b", drive_id=drive_id, rule_id="r", field="folder", kept=True, created=1
            )
        )


_BY_FILE = {
    "tags": file_tags.c.drive_id,
    "collections": collection_members.c.drive_id,
    "link names": member_link_names.c.drive_id,
    "tray items": item_files.c.drive_id,
    "locks": file_locks.c.drive_id,
    "from/for": file_assignments.c.drive_id,
    "summaries": file_summaries.c.drive_id,
    "fields": file_fields.c.drive_id,
    "rule outcomes": rule_outcomes.c.drive_id,
    "codes": file_assigned_codes.c.drive_id,
    "notes": notes.c.target_id,
    "checklist": checklist_items.c.target_id,
}


def test_reconnect_moves_everything_and_drops_the_old_row(app, moved):
    old, new, col = moved
    _give_everything(app, old)
    with app.engine.begin() as conn:
        conn.execute(insert(item_files).values(item_id=_item(app), drive_id=old))
        conn.execute(
            insert(member_link_names).values(collection_id=col.id, drive_id=old, link_name="x")
        )
    index(app)  # the content pass reads the new file meanwhile, as it does in the app
    [pair] = run(app).items
    preview = app.maintenance.reconnect([(old, new)], dry_run=True)
    assert [p.new_id for p in preview.pairs] == [new]
    assert app.repo.get(old) is not None  # a dry run changes nothing

    done = app.maintenance.reconnect([(pair.old_id, pair.new_id)])
    assert done.errors == [] and [p.old_id for p in done.pairs] == [old]
    assert app.repo.get(old) is None
    rec = app.repo.get(new)
    assert rec.path == f"{HOME}/renamed.txt" and not rec.missing
    with app.engine.connect() as conn:
        for what, column in _BY_FILE.items():
            ids = set(conn.execute(select(column)).scalars())
            assert old not in ids, what
            assert new in ids, what
        assert conn.execute(select(files.c.drive_id).where(files.c.drive_id == old)).first() is None
    assert app.tags.for_file(new) == ["tax"]
    assert app.notes.get("file", new) == "n"
    [hit] = search(app.engine, "heating")  # the file's text is still found, once
    assert hit.drive_id == new
    assert [h.drive_id for h in search(app.engine, "renamed")] == [new]
    assert run(app).items == []


def _item(app) -> int:
    from dam.db.tables import items

    with app.engine.begin() as conn:
        return conn.execute(
            insert(items).values(tray_id="bills", title="t", fields={}, created=time.time())
        ).inserted_primary_key[0]


def test_reconnect_refuses_what_does_not_hold(app, moved, fake_archive):
    old, new, _ = moved
    run(app)
    with pytest.raises(InvalidRequest):
        app.maintenance.reconnect([])
    with pytest.raises(InvalidRequest, match="more than once"):
        app.maintenance.reconnect([(old, new), (old, new)])
    with pytest.raises(InvalidRequest, match="not missing"):
        app.maintenance.reconnect([(new, old)])
    app.tags.add(new, ["own"])  # the new row has something of its own now
    with pytest.raises(InvalidRequest, match="of its own"):
        app.maintenance.reconnect([(old, new)])
    assert app.repo.get(old) is not None


def test_reconnect_refuses_a_file_changed_since_the_check(app, moved, fake_archive):
    old, new, _ = moved
    run(app)
    (fake_archive.root / HOME / "renamed.txt").write_bytes(b"heating bill april")
    with pytest.raises(InvalidRequest, match="changed"):
        app.maintenance.reconnect([(old, new)])


def test_an_ignored_pair_stays_out(app, moved):
    old, new, _ = moved
    run(app)
    app.maintenance.ignored.add("moved", f"{old}>{new}", f"{HOME}/renamed.txt")
    result = run(app)
    assert (result.items, result.total) == ([], 0)


def test_a_listed_pair_drops_out_once_reconnected_or_gone(app, moved, fake_archive):
    old, new, _ = moved
    job = app.maintenance.start("moved")
    job.join(15)
    rename(fake_archive, f"{HOME}/renamed.txt", f"{HOME}/again.txt")
    app.scan()
    result = app.maintenance.result_of(job)[1]
    assert (result.items, result.total) == ([], 0)


def test_api_moved_flow(app, moved):
    old, new, _ = moved
    with TestClient(create_api(app, None), base_url=BASE) as c:
        job = c.post("/api/maintenance/jobs", json={"kind": "moved"}, headers=H)
        assert job.status_code == 200, job.text
        for _ in range(100):
            body = c.get(f"/api/maintenance/jobs/{job.json()['job_id']}", headers=H).json()
            if body["state"] != "running":
                break
            time.sleep(0.05)
        [pair] = body["moved"]["items"]
        assert pair["moves"] == {"tags": 1, "collections": 1}
        choice = {"pairs": [{"old": old, "new": new}]}
        dry = c.post(
            "/api/maintenance/moved/reconnect", json={**choice, "dry_run": True}, headers=H
        )
        assert dry.status_code == 200 and dry.json()["dry_run"] is True
        assert app.repo.get(old) is not None
        done = c.post("/api/maintenance/moved/reconnect", json=choice, headers=H)
        assert done.status_code == 200 and done.json()["errors"] == []
        assert app.repo.get(old) is None
        again = c.post("/api/maintenance/moved/reconnect", json=choice, headers=H)
        assert again.status_code == 404
        ignore = {"kind": "moved", "key": f"{old}>{new}", "label": "renamed.txt"}
        assert c.post("/api/maintenance/ignored", json=ignore, headers=H).status_code == 200
