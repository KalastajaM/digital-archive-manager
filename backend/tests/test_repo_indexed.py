"""Folder listings, path moves, missing marks and the status counts use the path index
(no scan of the whole ``files`` table), and the status counts are kept between polls
until something is written."""

import re
import unicodedata
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from dam.extract.layout import Page1Layout
from dam.index.repo import FileRecord, FileRepo

_ON_FILES = re.compile(r"\b(SCAN|SEARCH) (TABLE )?files\b")
# a lookup by path or by drive id; any other way into ``files`` reads (nearly) all of it
_NARROW = re.compile(
    r"\bSEARCH (TABLE )?files USING (COVERING )?INDEX "
    r"(ix_files_path_nfc|sqlite_autoindex_files_\d) \((path|drive_id)"
)


def rec(drive_id: str, path: str, **kw) -> FileRecord:
    return FileRecord(drive_id=drive_id, path=path, **kw)


@contextmanager
def statements(engine):
    """The (statement, parameters) pairs run on ``engine`` inside the block."""
    seen: list[tuple[str, object]] = []

    def grab(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip().upper().startswith("EXPLAIN"):
            seen.append((statement, params))

    event.listen(engine, "before_cursor_execute", grab)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", grab)


def full_scans(engine, seen) -> list[str]:
    """The plan lines of ``seen`` that read ``files`` other than by a path range or
    lookup (a scan, or a "search" on an index nearly every row matches)."""
    out = []
    with engine.connect() as conn:
        for statement, params in seen:
            if not re.search(r"\bfiles\b", statement):
                continue
            plan = conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params).all()
            out += [
                f"{row[-1]}  <- {statement}"
                for row in plan
                if _ON_FILES.search(row[-1]) and not _NARROW.search(row[-1])
            ]
    return out


@pytest.fixture
def repo(engine):
    return FileRepo(engine, inbox="##. Organize")


def _tree(repo):
    nfd = unicodedata.normalize("NFD", "Kyynärpää")
    for i, (path, kw) in enumerate(
        [
            ("a", {"is_dir": True}),
            ("a b.pdf", {}),
            ("a.pdf", {}),
            ("a0", {}),
            ("a/x.pdf", {}),
            ("a/sub", {"is_dir": True}),
            ("a/sub/y.pdf", {}),
            ("a/sub/deeper/z.pdf", {}),
            ("a/gone.pdf", {"missing": True}),
            ("a/100%_done.pdf", {}),
            ("a/1000_done.pdf", {}),
            ("a/A.pdf", {}),
            ("a/orphan/w.pdf", {}),  # its folder has no row: not listed
            (f"a/{nfd}", {"is_dir": True}),
            (f"a/{nfd}/k.pdf", {}),
            ("%", {"is_dir": True}),
            ("%/p.pdf", {}),
            ("_x", {}),
            ("##. Organize", {"is_dir": True}),
            ("##. Organize/in.pdf", {}),
            ("top.pdf", {}),
            ("zz", {"is_dir": True, "missing": True}),
            ("zz/still.pdf", {}),
        ]
    ):
        repo.upsert(rec(f"d{i}", path, **kw))
    repo.upsert(rec("parked", "a/parked.pdf"))
    repo.park("a/parked.pdf")


def test_list_dir_same_children(repo):
    _tree(repo)
    kyy = unicodedata.normalize("NFC", "Kyynärpää")
    root = ["##. Organize", "%", "_x", "a", "a b.pdf", "a.pdf", "a0", "top.pdf"]
    assert [r.path_nfc for r in repo.list_dir("")] == root
    assert [r.path_nfc for r in repo.list_dir("a")] == [
        "a/100%_done.pdf",
        "a/1000_done.pdf",
        "a/A.pdf",
        f"a/{kyy}",
        "a/sub",
        "a/x.pdf",
    ]
    assert [r.path for r in repo.list_dir("a/sub")] == ["a/sub/y.pdf"]
    assert [r.path for r in repo.list_dir("a/sub/deeper")] == ["a/sub/deeper/z.pdf"]
    nfd = unicodedata.normalize("NFD", f"a/{kyy}")
    assert [r.path_nfc for r in repo.list_dir(nfd)] == [f"a/{kyy}/k.pdf"]
    assert [r.path for r in repo.list_dir("%")] == ["%/p.pdf"]
    assert [r.path for r in repo.list_dir("_")] == []
    assert [r.path for r in repo.list_dir("A")] == []  # case counts, as before
    assert [r.path for r in repo.list_dir("zz")] == ["zz/still.pdf"]
    assert repo.list_dir("nowhere") == []


def test_list_dir_empty_index(repo):
    assert repo.list_dir("") == []
    assert repo.list_dir("a") == []


def test_list_dir_uses_the_path_index(repo, engine):
    _tree(repo)
    for rel in ("", "a", "a/sub"):
        with statements(engine) as seen:
            repo.list_dir(rel)
        assert seen and full_scans(engine, seen) == []


def test_update_path_and_mark_missing_use_the_path_index(repo, engine):
    _tree(repo)
    with statements(engine) as seen:
        repo.update_path("a/sub", "a/moved")
        repo.mark_missing(0.0, subtree="a", skipped=["a/moved"])
        repo.count_subtree("a")
        repo.has_live_under("a")
        repo.park("a/x.pdf", descendants=True, except_under="a/sub")
    assert seen and full_scans(engine, seen) == []
    assert [r.path for r in repo.list_dir("a/moved")] == ["a/moved/y.pdf"]
    assert repo.by_path("a/moved/deeper/z.pdf") is not None
    assert repo.by_path("a b.pdf").missing is False  # "a b.pdf" is not under "a"


def test_by_folded_path_same_matches(repo, engine):
    _tree(repo)
    repo.upsert(rec("u1", "Docs/Straße.pdf"))
    repo.upsert(rec("u2", "docs/STRASSE.pdf"))
    repo.upsert(rec("u3", "DOCS/straße.PDF"))
    repo.upsert(rec("u4", "Docs/gone.pdf", missing=True))
    found = sorted(r.drive_id for r in repo.by_folded_path("docs/STRAßE.pdf"))
    assert found == ["u1", "u3"]  # "STRASSE" folds alike but is longer: left out, as before
    assert repo.by_folded_path("DOCS/GONE.PDF") == []
    nfd = unicodedata.normalize("NFD", "A/KYYNÄRPÄÄ/K.PDF")
    assert [r.path for r in repo.by_folded_path(nfd)] == [
        unicodedata.normalize("NFD", "a/Kyynärpää/k.pdf")
    ]
    assert [r.path for r in repo.by_folded_path("A/ORPHAN/W.PDF")] == ["a/orphan/w.pdf"]
    assert [r.path for r in repo.by_folded_path("ZZ/STILL.PDF")] == ["zz/still.pdf"]
    with statements(engine) as seen:
        repo.by_folded_path("A/SUB/Y.PDF")
    assert seen and full_scans(engine, seen) == []


def test_status_counts_kept_until_a_write(repo, engine):
    _tree(repo)
    first = (repo.counts(), repo.layout_progress(), repo.layout_unread())
    with statements(engine) as seen:
        again = (repo.counts(), repo.layout_progress(), repo.layout_unread())
    assert again == first
    assert seen == []  # an idle poll reads nothing


def test_status_counts_follow_every_write(repo):
    _tree(repo)
    before = repo.counts()
    repo.upsert(rec("n1", "##. Organize/new.pdf"))
    after = repo.counts()
    assert after["total"] == before["total"] + 1
    assert after["inbox"] == before["inbox"] + 1
    repo.mark_missing_path("##. Organize/new.pdf")
    assert repo.counts() == {**before, "missing": before["missing"] + 1}
    repo.code_folders = {"to pay": "PAY"}
    repo.upsert(rec("n2", "##. Organize/To Pay/bill.pdf"))
    assert repo.counts()["inbox"] == before["inbox"] + 1
    repo.code_folders = {}
    assert repo.counts()["inbox"] == before["inbox"]


def test_layout_progress_follows_writes(repo):
    repo.upsert(rec("p1", "x/a.pdf", index_state="indexed", sha256="h1"))
    assert repo.layout_progress() == (0, 1)
    assert repo.layout_unread() == (1, 0)
    repo.save_layout("p1", "h1", Page1Layout())
    assert repo.layout_progress() == (1, 1)
    assert repo.layout_unread() == (0, 0)
