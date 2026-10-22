import os
import unicodedata

import pytest
import xattr
from sqlalchemy import insert, select, text

from conftest import posix_names, posix_permissions
from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.db.tables import file_tags, file_text, files
from dam.index.driveid import DRIVE_ID_XATTR
from dam.index.repo import FileRepo, TagRepo
from dam.index.scanner import scan


def setup(fake_archive, engine):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    return paths, FileRepo(engine, inbox=paths.inbox)


def test_initial_scan_counts(fake_archive, engine):
    fake_archive.add("10. Financial/Banks/20240101_statement.pdf")
    fake_archive.add("##. Organize/scan.jpg")
    paths, repo = setup(fake_archive, engine)
    rep = scan(paths, repo)
    # 4 special folders + 10. Financial + Banks + 2 files
    assert rep.added == 8 and rep.moved == rep.updated == rep.missing == rep.rekeyed == 0
    f = repo.by_path("10. Financial/Banks/20240101_statement.pdf")
    assert f.drive_id == "fake-1" and f.ext == "pdf" and f.index_state == "pending"
    assert str(f.doc_date) == "2024-01-01" and f.size == 1
    d = repo.by_path("10. Financial")
    assert d.is_dir and d.ext is None
    again = scan(paths, repo)
    assert (again.added, again.moved, again.updated, again.missing) == (0, 0, 0, 0)


@posix_names
def test_ignores_ds_store_and_temp(fake_archive, engine):
    for name in (".DS_Store", "Icon\r", "~$x.docx", ".~lock.x#", "a.tmp"):
        fake_archive.add(f"##. Organize/{name}", drive_id=None)
    fake_archive.add("##. Organize/.tmp.drivedownload/part.pdf", drive_id=None)
    fake_archive.add("##. Organize/keep.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    assert [r.name for r in repo.list_dir("##. Organize")] == ["keep.pdf"]


def test_detects_external_move(fake_archive, engine):
    src = fake_archive.add("##. Organize/a.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    dst = fake_archive.root / "10. Financial" / "Banks" / "b.pdf"
    os.rename(src, dst)
    rep = scan(paths, repo)
    assert (rep.moved, rep.added, rep.missing) == (1, 0, 0)
    rec = repo.get("fake-1")
    assert rec.path == "10. Financial/Banks/b.pdf" and rec.name == "b.pdf" and not rec.missing


def test_detects_moved_folder_counts_once(fake_archive, engine):
    fake_archive.add("##. Organize/box/a.pdf")
    xattr.setxattr(fake_archive.root / "##. Organize" / "box", DRIVE_ID_XATTR, b"box-id")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(
        fake_archive.root / "##. Organize" / "box", fake_archive.root / "10. Financial" / "box"
    )
    rep = scan(paths, repo)
    assert (rep.moved, rep.added, rep.missing) == (1, 0, 0)
    assert repo.get("fake-1").path == "10. Financial/box/a.pdf"


def test_detects_content_change_sets_pending(fake_archive, engine):
    p = fake_archive.add("##. Organize/a.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    repo.set_index_state("fake-1", "indexed")
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE files SET sha256='abc' WHERE drive_id='fake-1'")
    p.write_bytes(b"longer content")
    rep = scan(paths, repo)
    assert rep.updated == 1
    rec = repo.get("fake-1")
    assert rec.index_state == "pending" and rec.sha256 is None and rec.size == 14


def test_unchanged_keeps_state(fake_archive, engine):
    fake_archive.add("##. Organize/a.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    repo.set_index_state("fake-1", "indexed")
    scan(paths, repo)
    assert repo.get("fake-1").index_state == "indexed"


def test_missing_marked_and_reappears(fake_archive, engine):
    p = fake_archive.add("##. Organize/a.pdf")
    keep = fake_archive.add("10. Financial/k.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    saved = p.read_bytes()
    os.rename(p, fake_archive.root.parent / "outside.pdf")
    rep = scan(paths, repo)
    assert rep.missing == 1 and repo.get("fake-1").missing
    assert repo.get("fake-2") is not None and not repo.get("fake-2").missing
    assert repo.list_dir("##. Organize") == []
    os.rename(fake_archive.root.parent / "outside.pdf", p)
    scan(paths, repo)
    assert not repo.get("fake-1").missing and not repo.get("fake-2").missing
    assert [r.path for r in repo.list_dir("##. Organize")] == ["##. Organize/a.pdf"]
    assert saved == b"x" and keep.exists()


def test_subtree_scan_scoped(fake_archive, engine):
    a = fake_archive.add("##. Organize/a.pdf")
    b = fake_archive.add("10. Financial/b.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(a, fake_archive.root.parent / "outside-a")
    os.rename(b, fake_archive.root.parent / "outside-b")
    rep = scan(paths, repo, subtree="##. Organize")
    assert rep.missing == 1
    assert repo.get("fake-1").missing and not repo.get("fake-2").missing
    assert not repo.by_path("##. Organize").missing  # the subtree folder itself stays


def test_rekey_local_id(fake_archive, engine):
    p = fake_archive.add("##. Organize/a.pdf", drive_id=None)
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    local = repo.by_path("##. Organize/a.pdf")
    assert local.drive_id.startswith("local:")
    xattr.setxattr(p, DRIVE_ID_XATTR, b"real-id")
    rep = scan(paths, repo)
    assert rep.rekeyed == 1 and rep.added == 0
    assert repo.get(local.drive_id) is None
    assert repo.by_path("##. Organize/a.pdf").drive_id == "real-id"


def test_new_entry_replaces_stale_row_on_same_path(fake_archive, engine):
    p = fake_archive.add("##. Organize/a.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(p, p.with_name("elsewhere.pdf"))
    fake_archive.add("##. Organize/a.pdf", content=b"other", drive_id="brand-new")
    rep = scan(paths, repo)
    assert repo.by_path("##. Organize/a.pdf").drive_id == "brand-new"
    assert rep.added == 1 and rep.moved == 1


def test_moved_entry_takes_stale_path(fake_archive, engine):
    a = fake_archive.add("##. Organize/a.pdf")
    b = fake_archive.add("##. Organize/b.pdf")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(a, a.with_name("gone.pdf"))  # fake-1 leaves; row for a.pdf is stale
    os.rename(b, a)  # fake-2 takes a.pdf
    scan(paths, repo)
    assert repo.by_path("##. Organize/a.pdf").drive_id == "fake-2"
    assert repo.get("fake-1").path == "##. Organize/gone.pdf"


def test_symlink_recorded_not_followed(fake_archive, engine):
    for n in "abc":
        fake_archive.add(f"10. Financial/Banks/{n}.pdf")
    link = fake_archive.link("##. Ongoing/Banks", "10. Financial/Banks")
    outside = fake_archive.root / "##. Ongoing" / "ext"
    outside.symlink_to("/nonexistent/elsewhere")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    row = repo.by_path("##. Ongoing/Banks")
    assert row.is_link and row.index_state == "unsupported"
    assert row.link_target == "10. Financial/Banks"
    target = repo.by_path("##. Ongoing/ext").link_target
    assert target.replace("\\", "/").endswith("/nonexistent/elsewhere")  # a drive letter on Windows
    assert repo.by_path("##. Ongoing/Banks/a.pdf") is None
    assert len(repo.list_dir("10. Financial/Banks")) == 3
    with engine.connect() as conn:
        assert conn.execute(select(files).where(files.c.name == "a.pdf")).all().__len__() == 1
    assert link.is_symlink()
    os.symlink("../10. Financial/Banks", fake_archive.root / "##. Ongoing" / "rel")
    scan(paths, repo)
    assert repo.by_path("##. Ongoing/rel").link_target == "10. Financial/Banks"


def test_nfd_name_on_disk_roundtrip(fake_archive, engine):
    nfd = unicodedata.normalize("NFD", "Kyynärpää.pdf")
    fake_archive.add(f"##. Organize/{nfd}")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    rep = scan(paths, repo)
    assert rep.added == 0 and rep.moved == 0
    assert repo.by_path(unicodedata.normalize("NFC", f"##. Organize/{nfd}")) is not None


OUT = "outside"


def seed_children(engine, drive_id, path, body="hello"):
    with engine.begin() as conn:
        conn.execute(insert(file_text), {"drive_id": drive_id, "text": body})
        # the scan already wrote a name-only FTS row; replace it, as save_content does
        conn.execute(text("DELETE FROM file_fts WHERE drive_id = :d"), {"d": drive_id})
        conn.execute(
            text("INSERT INTO file_fts(drive_id, name, path, text) VALUES (:d, 'n', :p, :t)"),
            {"d": drive_id, "p": path, "t": body},
        )
    TagRepo(engine).add(drive_id, ["tagged"])


def children_counts(engine, drive_id):
    with engine.connect() as conn:
        return (
            conn.execute(select(file_text).where(file_text.c.drive_id == drive_id)).all().__len__(),
            conn.execute(select(file_tags).where(file_tags.c.drive_id == drive_id)).all().__len__(),
            conn.execute(text("SELECT 1 FROM file_fts WHERE drive_id = :d"), {"d": drive_id})
            .all()
            .__len__(),
        )


def test_unclaimed_parked_row_purged_with_children(fake_archive, engine):
    old = fake_archive.add("A/a.pdf", drive_id="OLD")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    seed_children(engine, "OLD", "A/a.pdf", "oldtext")
    os.rename(old, fake_archive.root.parent / OUT)
    fake_archive.add("A/a.pdf", content=b"new", drive_id="NEW")
    scan(paths, repo)
    assert repo.get("OLD") is None
    assert children_counts(engine, "OLD") == (0, 0, 0)
    with engine.connect() as conn:
        hits = conn.execute(
            text("SELECT drive_id FROM file_fts WHERE file_fts MATCH 'oldtext'")
        ).all()
    assert hits == []


def test_rename_chain_keeps_children_and_fts_path(fake_archive, engine):
    a = fake_archive.add("A/a.pdf", drive_id="OLD")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    seed_children(engine, "OLD", "A/a.pdf")
    os.rename(a, a.with_name("b.pdf"))
    fake_archive.add("A/a.pdf", content=b"new", drive_id="NEW")
    scan(paths, repo)
    assert repo.get("OLD").path == "A/b.pdf" and not repo.get("OLD").missing
    assert children_counts(engine, "OLD") == (1, 1, 1)
    with engine.connect() as conn:
        fts = conn.execute(text("SELECT path FROM file_fts WHERE drive_id = 'OLD'")).scalar_one()
    assert fts == "A/b.pdf"


def test_fts_path_updated_after_external_move(fake_archive, engine):
    a = fake_archive.add("A/a.pdf", drive_id="D")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    seed_children(engine, "D", "A/a.pdf")
    os.rename(a, fake_archive.root / "10. Financial" / "z.pdf")
    scan(paths, repo)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, path FROM file_fts WHERE drive_id = 'D'")).one()
    assert tuple(row) == ("z.pdf", "10. Financial/z.pdf")


def test_folder_moved_onto_stale_descendants(fake_archive, engine):
    for folder in ("A", "B"):
        fake_archive.add(f"{folder}/box/x.pdf", drive_id=f"x-{folder}")
        xattr.setxattr(fake_archive.root / folder / "box", DRIVE_ID_XATTR, f"box-{folder}".encode())
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(fake_archive.root / "B" / "box", fake_archive.root.parent / "gone-box")
    scan(paths, repo)  # B/box and its x.pdf are now missing rows
    os.rename(fake_archive.root / "A" / "box", fake_archive.root / "B" / "box")
    rep = scan(paths, repo)
    assert rep.moved == 1  # the folder; x.pdf moves with it
    assert repo.get("x-A").path == "B/box/x.pdf"
    again = scan(paths, repo)
    assert (again.added, again.moved, again.updated) == (0, 0, 0)


def test_subtree_scan_nfd_folder_keeps_spelling(fake_archive, engine):
    nfd = unicodedata.normalize("NFD", "Käsi")
    fake_archive.add(f"{nfd}/a.pdf", drive_id="D")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    rep = scan(paths, repo, subtree=unicodedata.normalize("NFC", "Käsi"))
    assert rep.moved == 0 and rep.added == 0
    assert repo.get("D").path == f"{nfd}/a.pdf"
    rep = scan(paths, repo)
    assert rep.moved == 0 and repo.get("D").path == f"{nfd}/a.pdf"


def test_subtree_scan_keeps_parked_rows(fake_archive, engine):
    xa = fake_archive.add("A/a.pdf", drive_id="X")
    yb = fake_archive.add("A/b.pdf", drive_id="Y")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    seed_children(engine, "X", "A/a.pdf")
    (fake_archive.root / "B").mkdir(exist_ok=True)
    os.rename(xa, fake_archive.root / "B" / "a.pdf")
    os.rename(yb, xa)
    scan(paths, repo, subtree="A")
    assert repo.get("X") is not None and children_counts(engine, "X") == (1, 1, 1)
    assert repo.get("Y").path == "A/a.pdf"
    scan(paths, repo)
    assert repo.get("X").path == "B/a.pdf" and not repo.get("X").missing
    assert children_counts(engine, "X") == (1, 1, 1)


def test_no_xattr_inherits_local_or_matching_row(fake_archive, engine):
    p = fake_archive.add("A/a.pdf", drive_id=None)
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    local = repo.by_path("A/a.pdf").drive_id
    rep = scan(paths, repo)
    assert rep.added == 0 and repo.by_path("A/a.pdf").drive_id == local
    # a real-id row whose file lost its xattr but is unchanged keeps its id
    q = fake_archive.add("A/q.pdf", drive_id="REAL")
    scan(paths, repo)
    xattr.removexattr(q, DRIVE_ID_XATTR)
    rep = scan(paths, repo)
    assert rep.added == 0 and repo.by_path("A/q.pdf").drive_id == "REAL"
    assert p.exists()


def test_no_xattr_different_file_does_not_inherit(fake_archive, engine):
    q = fake_archive.add("A/q.pdf", drive_id="REAL")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    seed_children(engine, "REAL", "A/q.pdf")
    os.rename(q, fake_archive.root.parent / OUT)
    fake_archive.add("A/q.pdf", content=b"something else", drive_id=None)
    rep = scan(paths, repo)
    assert rep.added == 1
    new = repo.by_path("A/q.pdf")
    assert new.drive_id.startswith("local:") and new.index_state == "pending"
    assert repo.get("REAL") is None  # unclaimed, purged by the full scan


def test_move_plus_content_change_recomputes_ext(fake_archive, engine):
    a = fake_archive.add("A/a.pdf", drive_id="D")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(a, a.with_name("a.jpg"))
    a.with_name("a.jpg").write_bytes(b"changed content")
    scan(paths, repo)
    rec = repo.get("D")
    assert (rec.name, rec.ext, rec.index_state) == ("a.jpg", "jpg", "pending")


def test_duplicate_drive_id_in_one_walk(fake_archive, engine):
    fake_archive.add("A/a.pdf", drive_id="DUP")
    fake_archive.add("A/b.pdf", drive_id="DUP")
    paths, repo = setup(fake_archive, engine)
    rep = scan(paths, repo)
    first, second = repo.by_path("A/a.pdf"), repo.by_path("A/b.pdf")
    assert first.drive_id == "DUP" and second.drive_id.startswith("local:")
    assert rep.moved == 0
    again = scan(paths, repo)
    assert (again.added, again.moved) == (0, 0)


def test_new_idless_folder_does_not_inherit_moved_folder_id(fake_archive, engine):
    fake_archive.add("Taxes/old.pdf", drive_id="T1")
    xattr.setxattr(fake_archive.root / "Taxes", DRIVE_ID_XATTR, b"TAXES")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    (fake_archive.root / "Zarc").mkdir()
    os.rename(fake_archive.root / "Taxes", fake_archive.root / "Zarc" / "Taxes")
    fake_archive.add("Taxes/new.pdf", drive_id=None)
    scan(paths, repo)
    assert repo.get("TAXES").path == "Zarc/Taxes"
    assert repo.get("T1").path == "Zarc/Taxes/old.pdf"
    new_dir, new_file = repo.by_path("Taxes"), repo.by_path("Taxes/new.pdf")
    assert new_dir.drive_id.startswith("local:") and new_file is not None
    with engine.connect() as conn:
        live = conn.execute(select(files.c.path).where(files.c.missing.is_not(True))).scalars()
        ghosts = [r for r in live if not (fake_archive.root / r).exists()]
    assert ghosts == []
    again = scan(paths, repo)
    assert (again.added, again.moved, again.updated, again.missing) == (0, 0, 0, 0)


def test_inherited_real_id_blocks_later_owner(fake_archive, engine):
    q = fake_archive.add("A/q.pdf", drive_id="REAL")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    xattr.removexattr(q, DRIVE_ID_XATTR)
    fake_archive.add("Z/q.pdf", content=b"copy", drive_id="REAL")
    rep = scan(paths, repo)
    assert rep.moved == 0
    assert repo.by_path("A/q.pdf").drive_id == "REAL"
    assert repo.by_path("Z/q.pdf").drive_id.startswith("local:")


def test_scans_are_serialised(fake_archive, engine, monkeypatch):
    import threading
    import time

    from dam.index import scanner

    fake_archive.add("##. Organize/a.pdf")
    paths, repo = setup(fake_archive, engine)
    guard = threading.Lock()
    state = {"active": 0, "max": 0}
    entered = threading.Event()
    real = scanner._scan

    def spy(*args):
        with guard:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        entered.set()
        time.sleep(0.2)  # hold the scan open so an unserialised second scan would overlap
        try:
            return real(*args)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(scanner, "_scan", spy)
    results = []
    first = threading.Thread(target=lambda: results.append(scan(paths, repo)))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=lambda: results.append(scan(paths, repo)))
    second.start()
    first.join(30)
    second.join(30)
    assert len(results) == 2 and state["max"] == 1


# --- name search before content indexing (final review item 2) ---------------


def _fts_rows(engine, drive_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT name, path, text FROM file_fts WHERE drive_id = :id"), {"id": drive_id}
        ).all()


def test_scan_alone_makes_names_searchable(fake_archive, engine):
    from dam.search import search

    fake_archive.add("##. Organize/File_000.pdf", drive_id="id-f")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    assert [h.drive_id for h in search(engine, "File_000")] == ["id-f"]
    banks = repo.by_path("10. Financial/Banks").drive_id
    assert [h.drive_id for h in search(engine, "Banks")] == [banks]  # folders too


def test_rescan_after_external_rename_updates_name_search(fake_archive, engine):
    from dam.search import search

    src = fake_archive.add("##. Organize/File_000.pdf", drive_id="id-f")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    os.rename(src, src.with_name("Taxcard.pdf"))
    scan(paths, repo)
    assert [h.drive_id for h in search(engine, "Taxcard")] == ["id-f"]
    assert search(engine, "File_000") == []
    assert len(_fts_rows(engine, "id-f")) == 1


def test_content_indexed_later_keeps_one_fts_row(fake_archive, engine):
    from dam.extract.base import ExtractedText
    from dam.search import search

    fake_archive.add("##. Organize/File_000.pdf", drive_id="id-f")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    assert _fts_rows(engine, "id-f") == [("File_000.pdf", "##. Organize/File_000.pdf", "")]
    repo.save_content("id-f", None, ExtractedText("heating oil", "test"), "indexed")
    assert len(_fts_rows(engine, "id-f")) == 1
    assert [h.drive_id for h in search(engine, "heating")] == ["id-f"]
    scan(paths, repo)  # an unchanged rescan leaves the text alone
    assert _fts_rows(engine, "id-f") == [
        ("File_000.pdf", "##. Organize/File_000.pdf", "heating oil")
    ]


# --- unavailable archive root (final review item 3) ---------------------------


def _missing_rows(engine) -> int:
    with engine.connect() as conn:
        return len(conn.execute(select(files).where(files.c.missing.is_(True))).all())


def test_scan_aborts_when_root_is_gone_and_self_heals(fake_archive, engine, tmp_path):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    assert scan(paths, repo).aborted is False
    away = tmp_path / "archive-away"
    os.rename(fake_archive.root, away)  # Drive unmounted / folder renamed
    for subtree in ("", "##. Organize"):
        rep = scan(paths, repo, subtree)
        assert rep.aborted is True and rep.missing == 0
    assert _missing_rows(engine) == 0
    assert repo.by_path("##. Organize/a.pdf") is not None
    os.rename(away, fake_archive.root)
    rep = scan(paths, repo)
    assert rep.aborted is False and (rep.added, rep.missing) == (0, 0)
    assert repo.get("id-a").missing is False


def test_scan_aborts_when_root_vanishes_mid_run(fake_archive, engine, tmp_path, monkeypatch):
    from dam.index import scanner as scanner_mod

    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    fake_archive.add("10. Financial/Banks/b.pdf", drive_id="id-b")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    real_gather = scanner_mod._Scan.gather
    moved = []

    def gather_then_unmount(self, *args, **kwargs):
        item = real_gather(self, *args, **kwargs)
        if not moved:
            os.rename(fake_archive.root, tmp_path / "archive-away")
            moved.append(True)
        return item

    monkeypatch.setattr(scanner_mod._Scan, "gather", gather_then_unmount)
    rep = scan(paths, repo)
    assert rep.aborted is True and rep.missing == 0
    assert _missing_rows(engine) == 0


def test_missing_subtree_with_root_available_still_marks_missing(fake_archive, engine):
    a = fake_archive.add("10. Financial/Banks/b.pdf", drive_id="id-b")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    a.unlink()
    rep = scan(paths, repo, "10. Financial/Banks/b.pdf")
    assert rep.aborted is False and rep.missing == 1


needs_non_root = pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() == 0, reason="root can read mode-000 dirs"
)


@posix_permissions
@needs_non_root
def test_unreadable_subfolder_not_marked_missing(fake_archive, engine):
    fake_archive.add("10. Financial/Banks/b.pdf", drive_id="id-b")
    fake_archive.add("10. Financial 2/c.pdf", drive_id="id-c")
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    locked = fake_archive.root / "10. Financial"
    fake_archive.add("##. Organize/new.pdf", drive_id="id-new")
    (fake_archive.root / "10. Financial 2" / "c.pdf").unlink()
    os.chmod(locked, 0o000)
    try:
        rep = scan(paths, repo)
    finally:
        os.chmod(locked, 0o755)
    assert rep.aborted is False and rep.skipped == ["10. Financial"]
    assert repo.get("id-b").missing is False
    assert repo.by_path("10. Financial").missing is False
    assert repo.get("id-new") is not None  # other folders scanned normally
    assert repo.get("id-c").missing is True  # sibling with the same name prefix is not shielded


@needs_non_root
def test_subtree_start_unreadable_aborts(fake_archive, engine, monkeypatch):
    fake_archive.add("10. Financial/Banks/b.pdf", drive_id="id-b")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    real = os.lstat

    def deny(path, *a, **k):
        if str(path).endswith("Banks"):
            raise PermissionError(13, "denied")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "lstat", deny)
    rep = scan(paths, repo, "10. Financial/Banks")
    assert rep.aborted is True and rep.missing == 0
    assert _missing_rows(engine) == 0


def test_empty_root_with_indexed_rows_aborts(fake_archive, engine, tmp_path):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    scan(paths, repo)
    away = tmp_path / "stash"
    away.mkdir()
    for child in list(fake_archive.root.iterdir()):
        os.rename(child, away / child.name)  # mount lists nothing
    rep = scan(paths, repo)
    assert rep.aborted is True and rep.missing == 0
    assert _missing_rows(engine) == 0
    for child in list(away.iterdir()):
        os.rename(child, fake_archive.root / child.name)
    assert scan(paths, repo).aborted is False
