import unicodedata
from datetime import date

from sqlalchemy import insert, select, text

from conftest import put_fts_row
from dam.db.tables import file_tags, file_text, files
from dam.index.repo import FileRecord, FileRepo, TagRepo


def rec(drive_id: str, path: str, **kw) -> FileRecord:
    return FileRecord(drive_id=drive_id, path=path, **kw)


def test_upsert_get(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    r = rec("d1", "A/Doc.PDF", size=5, mtime=1.5, doc_date=date(2020, 1, 2), last_seen=3.0)
    repo.upsert(r)
    got = repo.get("d1")
    assert got == r
    assert got.name == "Doc.PDF" and got.ext == "pdf" and got.path_nfc == "A/Doc.PDF"
    assert repo.get("nope") is None
    r.size = 9
    repo.upsert(r)
    assert repo.get("d1").size == 9


def test_by_path_nfc(engine):
    nfd = unicodedata.normalize("NFD", "Kyynärpää.pdf")
    nfc_ = unicodedata.normalize("NFC", nfd)
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", f"x/{nfd}"))
    got = repo.by_path(f"x/{nfc_}")
    assert got is not None and got.path == f"x/{nfd}"
    assert got.path_nfc == f"x/{nfc_}"


def test_update_path_dir_descendants(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "a/b", is_dir=True))
    repo.upsert(rec("d2", "a/b/c.pdf"))
    repo.upsert(rec("d3", "a/bc.pdf"))
    repo.update_path("a/b", "z/B")
    assert repo.get("d1").path == "z/B"
    assert repo.get("d2").path == "z/B/c.pdf"
    assert repo.get("d3").path == "a/bc.pdf"


def test_list_dir_direct_children_not_missing(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "a", is_dir=True))
    repo.upsert(rec("d2", "a/x.pdf"))
    repo.upsert(rec("d3", "a/sub/y.pdf"))
    repo.upsert(rec("d4", "a/gone.pdf", missing=True))
    repo.upsert(rec("d5", "top.pdf"))
    assert [r.path for r in repo.list_dir("a")] == ["a/x.pdf"]
    assert [r.path for r in repo.list_dir("")] == ["a", "top.pdf"]


def test_next_for_content_inbox_first(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "aaa/1.pdf"))
    repo.upsert(rec("d2", "##. Organize/z.pdf"))
    repo.upsert(rec("d3", "##. Organize/sub/a.pdf"))
    repo.upsert(rec("d4", "##. Organizer/x.pdf"))
    repo.upsert(rec("d5", "b/cloud.pdf", index_state="cloud_pending", retry_at=50.0))
    repo.upsert(rec("d6", "b/later.pdf", index_state="cloud_pending", retry_at=500.0))
    repo.upsert(rec("d7", "b/done.pdf", index_state="indexed"))
    repo.upsert(rec("d8", "b/gone.pdf", missing=True))
    repo.upsert(rec("d9", "b/dir", is_dir=True))
    repo.upsert(rec("d10", "b/link", is_link=True))
    got = [r.path for r in repo.next_for_content(10, now=100.0)]
    assert got == [
        "##. Organize/sub/a.pdf",
        "##. Organize/z.pdf",
        "##. Organizer/x.pdf",
        "aaa/1.pdf",
        "b/cloud.pdf",
    ]
    assert len(repo.next_for_content(2, now=100.0)) == 2


def test_set_index_state(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "a.pdf"))
    repo.set_index_state("d1", "cloud_pending", retry_at=7.0)
    got = repo.get("d1")
    assert (got.index_state, got.retry_at) == ("cloud_pending", 7.0)


def test_mark_missing_subtree(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "a/x.pdf", last_seen=1.0))
    repo.upsert(rec("d2", "ab/x.pdf", last_seen=1.0))
    repo.upsert(rec("d3", "a/y.pdf", last_seen=9.0))
    assert repo.mark_missing(5.0, "a") == 1
    assert repo.get("d1").missing and not repo.get("d2").missing and not repo.get("d3").missing
    assert repo.mark_missing(5.0) == 1  # d2


def test_rekey_carries_children(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("local:1", "a.pdf"))
    with engine.begin() as conn:
        conn.execute(insert(file_text), {"drive_id": "local:1", "text": "hello"})
        put_fts_row(conn, "local:1", "a", "a", "t")
    TagRepo(engine).add("local:1", ["x"])
    repo.rekey("local:1", "real")
    assert repo.get("local:1") is None and repo.get("real").path == "a.pdf"
    assert TagRepo(engine).for_file("real") == ["x"]
    with engine.connect() as conn:
        assert conn.execute(select(file_text.c.drive_id)).scalar_one() == "real"
        assert conn.execute(text("SELECT drive_id FROM file_fts")).scalar_one() == "real"


def test_upsert_drops_stale_row_with_children(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("old", "a.pdf"))
    with engine.begin() as conn:
        conn.execute(insert(file_text), {"drive_id": "old", "text": "hello"})
        put_fts_row(conn, "old", "a", "a", "t")
    TagRepo(engine).add("old", ["x"])
    repo.upsert(rec("new", "a.pdf"))
    assert repo.get("old") is None and repo.by_path("a.pdf").drive_id == "new"
    with engine.connect() as conn:
        assert conn.execute(select(file_text)).all() == []
        assert conn.execute(select(file_tags)).all() == []
        assert conn.execute(text("SELECT * FROM file_fts")).all() == []
        assert conn.execute(select(files.c.drive_id)).scalars().all() == ["new"]


def test_tags(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("d1", "a.pdf"))
    tags = TagRepo(engine)
    tags.add("d1", ["tax", "bank"])
    tags.add("d1", ["tax"])
    assert tags.for_file("d1") == ["bank", "tax"]
    assert tags.for_file("none") == []


def test_park_removes_row_from_lookups_and_fts_path(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("old", "a.pdf"))
    with engine.begin() as conn:
        put_fts_row(conn, "old", "a", "a.pdf", "t")
    repo.park("a.pdf", keep_id="new")
    assert repo.by_path("a.pdf") is None and repo.list_dir("") == []
    assert repo.get("old").missing
    with engine.connect() as conn:
        assert conn.execute(text("SELECT path FROM file_fts")).scalar_one() == ""
    repo.purge_parked()
    assert repo.get("old") is None


def test_update_path_refreshes_last_seen_and_clears_missing(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(FileRecord(drive_id="d1", path="a/x.pdf", last_seen=1.0))
    repo.mark_missing(2.0)
    assert repo.get("d1").missing
    repo.update_path("a/x.pdf", "b/x.pdf")
    row = repo.get("d1")
    assert not row.missing and row.last_seen > 1000.0


def test_counts(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    assert repo.counts() == {"total": 0, "inbox": 0, "missing": 0}
    repo.upsert(rec("d1", "##. Organize/a.pdf"))
    repo.upsert(rec("d2", "##. Organize/sub/b.pdf", index_state="indexed"))  # not directly in
    repo.upsert(rec("d3", "x/c.pdf", index_state="error"))
    repo.upsert(rec("d4", "x/gone.pdf", missing=True))
    repo.upsert(rec("d5", "x", is_dir=True, index_state="unsupported"))
    repo.upsert(rec("d6", "##. Organize/l.pdf", is_link=True, index_state="unsupported"))
    repo.upsert(rec("d7", "x/parked.pdf"))
    repo.park("x/parked.pdf")
    assert repo.counts() == {
        "total": 3,
        "inbox": 1,
        "missing": 1,
        "pending": 1,
        "indexed": 1,
        "error": 1,
    }
