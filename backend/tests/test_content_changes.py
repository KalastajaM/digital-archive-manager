"""Content change detection: a file whose bytes differ from what dam last knew."""

import os

from sqlalchemy import select

from dam.db.tables import content_changes
from dam.index.scanner import scan
from test_api import LOCAL_ORIGIN, make_client
from test_content import NOW, setup

REL = "10. Financial/rental agreement.txt"
ID = "d1"


def _save(fake_archive, content, rel=REL, drive_id=ID, ahead=10):
    """Save the file as an editor does: new bytes (or the same), and a later mtime."""
    path = fake_archive.add(rel, content, drive_id=drive_id)
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + ahead))
    return path


def _sync(paths, repo, indexer):
    scan(paths, repo)
    indexer.run_once(now=NOW)


def _indexed(fake_archive, engine, content=b"first"):
    paths, repo, indexer = setup(fake_archive, engine)
    fake_archive.add(REL, content, drive_id=ID)
    _sync(paths, repo, indexer)
    assert repo.get(ID).sha256 is not None
    return paths, repo, indexer


def test_a_new_file_is_no_change(fake_archive, engine):
    _, repo, _ = _indexed(fake_archive, engine)
    assert repo.content_changes() == ([], 0)
    assert repo.content_change(ID) is None


def test_new_bytes_are_a_change(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    before = repo.get(ID)
    _save(fake_archive, b"second, longer")
    _sync(paths, repo, indexer)
    rows, count = repo.content_changes()
    assert count == 1
    row = rows[0]
    assert (row.drive_id, row.path, row.name) == (ID, REL, "rental agreement.txt")
    assert (row.was_size, row.was_mtime) == (before.size, before.mtime)
    now = repo.get(ID)
    assert (row.size, row.mtime) == (now.size, now.mtime)
    assert row.detected_at > 0
    assert repo.content_change(ID) == row


def test_a_touch_is_no_change(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"first")
    _sync(paths, repo, indexer)
    assert repo.content_changes() == ([], 0)
    with engine.connect() as conn:  # nothing is left waiting either
        assert conn.execute(select(content_changes)).all() == []


def test_nothing_shows_before_the_read(fake_archive, engine):
    paths, repo, _ = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    scan(paths, repo)
    assert repo.get(ID).sha256 is None
    assert repo.content_changes() == ([], 0)


def test_changed_back_clears_the_notice(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    assert repo.content_changes()[1] == 1
    _save(fake_archive, b"first", ahead=20)
    _sync(paths, repo, indexer)
    assert repo.content_changes() == ([], 0)


def test_several_saves_are_one_notice_from_the_first_content(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    was = repo.get(ID)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    _save(fake_archive, b"third one", ahead=20)
    _sync(paths, repo, indexer)
    rows, count = repo.content_changes()
    assert count == 1
    assert rows[0].was_size == was.size and rows[0].size == len(b"third one")


def test_two_saves_before_a_read_keep_the_known_content(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    was = repo.get(ID)
    _save(fake_archive, b"second")
    scan(paths, repo)
    _save(fake_archive, b"third", ahead=20)
    _sync(paths, repo, indexer)
    assert repo.content_changes()[0][0].was_mtime == was.mtime


def test_a_file_never_read_has_nothing_to_compare_with(fake_archive, engine):
    paths, repo, indexer = setup(fake_archive, engine)
    fake_archive.add(REL, b"first", drive_id=ID)
    scan(paths, repo)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    assert repo.get(ID).sha256 is not None
    assert repo.content_changes() == ([], 0)


def test_a_move_is_no_change(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    src = fake_archive.root / REL
    src.rename(src.with_name("moved.txt"))
    _sync(paths, repo, indexer)
    assert repo.get(ID).path.endswith("moved.txt")
    assert repo.content_changes() == ([], 0)


def test_a_file_in_the_inbox_is_still_arriving(fake_archive, engine):
    paths, repo, indexer = setup(fake_archive, engine)
    rel = f"{paths.inbox}/scan.txt"
    fake_archive.add(rel, b"part", drive_id=ID)
    _sync(paths, repo, indexer)
    _save(fake_archive, b"part and the rest", rel=rel)
    _sync(paths, repo, indexer)
    assert repo.content_changes() == ([], 0)


def test_seen_and_undo(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    assert repo.see_changes([ID, "nobody"]) == [ID]
    assert repo.content_changes() == ([], 0)
    assert repo.see_changes([ID]) == []
    repo.unsee_changes([ID])
    assert repo.content_changes()[1] == 1


def test_a_change_after_seen_is_a_new_notice_from_the_seen_content(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    repo.see_changes([ID])
    seen = repo.get(ID)
    _save(fake_archive, b"third one", ahead=20)
    _sync(paths, repo, indexer)
    rows, count = repo.content_changes()
    assert count == 1 and rows[0].was_mtime == seen.mtime
    # and going back to what was seen last clears it
    _save(fake_archive, b"second", ahead=30)
    _sync(paths, repo, indexer)
    assert repo.content_changes() == ([], 0)


def test_gone_and_excluded_files_are_left_out(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    assert repo.content_changes(exclude=["10. Financial"]) == ([], 0)
    (fake_archive.root / REL).unlink()
    scan(paths, repo)
    assert repo.get(ID).missing
    assert repo.content_changes() == ([], 0)


def test_rekey_carries_the_notice_and_forget_removes_it(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    _sync(paths, repo, indexer)
    repo.rekey(ID, "d2")
    assert repo.content_change("d2") is not None
    repo.forget_rows(["d2"])
    with engine.connect() as conn:
        assert conn.execute(select(content_changes)).all() == []


def test_the_duplicate_checks_hash_settles_it_too(fake_archive, engine):
    paths, repo, indexer = _indexed(fake_archive, engine)
    _save(fake_archive, b"second")
    scan(paths, repo)
    rec = repo.get(ID)
    repo.save_hash(ID, "another-hash", (rec.size, rec.mtime))
    assert repo.content_changes()[1] == 1


def _changed_in_app(app, fake_archive, rel=REL, drive_id=ID):
    fake_archive.add(rel, b"first", drive_id=drive_id)
    scan(app.paths, app.repo)
    app.content.run_once(now=NOW)
    _save(fake_archive, b"second", rel=rel, drive_id=drive_id)
    scan(app.paths, app.repo)
    app.content.run_once(now=NOW)


def test_api_today_detail_seen_and_undo(app, fake_archive):
    _changed_in_app(app, fake_archive)
    with make_client(app) as c:
        out = c.get("/api/today").json()["content_changes"]
        assert out["count"] == 1 and out["rows"][0]["drive_id"] == ID
        assert c.get(f"/api/files/{ID}").json()["content_change"]["path"] == REL

        seen = c.post("/api/content-changes/seen", json={"drive_ids": [ID]}, headers=LOCAL_ORIGIN)
        assert seen.json() == {"drive_ids": [ID]}
        assert c.get("/api/today").json()["content_changes"] == {"count": 0, "rows": []}
        assert c.get(f"/api/files/{ID}").json()["content_change"] is None

        c.post("/api/content-changes/unseen", json={"drive_ids": [ID]}, headers=LOCAL_ORIGIN)
        assert c.get("/api/today").json()["content_changes"]["count"] == 1

        # no ids: every open one
        every = c.post("/api/content-changes/seen", json={}, headers=LOCAL_ORIGIN)
        assert every.json() == {"drive_ids": [ID]}


def test_today_shows_the_newest_few_and_counts_all(app, fake_archive):
    for i in range(10):
        _changed_in_app(app, fake_archive, rel=f"10. Financial/f{i}.txt", drive_id=f"d{i}")
    with make_client(app) as c:
        out = c.get("/api/today").json()["content_changes"]
    assert out["count"] == 10 and len(out["rows"]) == 8


def test_search_is_changed_agrees_with_today(app, fake_archive):
    _changed_in_app(app, fake_archive)
    fake_archive.add("10. Financial/other.txt", b"same", drive_id="other")
    scan(app.paths, app.repo)
    assert [h.drive_id for h in app.search("is:changed")] == [ID]
    assert {h.drive_id for h in app.search("-is:changed type:text")} >= {"other"}
    app.repo.see_changes([ID])
    assert app.search("is:changed") == []
    app.repo.unsee_changes([ID])
    # in To Delete: on neither
    src = fake_archive.root / REL
    dest = fake_archive.root / app.paths.quarantines[0] / src.name
    src.rename(dest)
    scan(app.paths, app.repo)
    assert app.search("is:changed") == []
    with make_client(app) as c:
        assert c.get("/api/today").json()["content_changes"]["count"] == 0
