"""Each extra archive folder has its own ``##. To Delete``: marking a file there keeps it
on its own disk, and the To Delete views list every folder's."""

import time

import pytest
from sqlalchemy import select

from dam.core.paths import ArchivePaths
from dam.db.tables import operations
from dam.ops.model import OpKind
from dam.services.errors import InvalidRequest

QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


def test_quarantine_helpers(extra_folder, app):
    paths: ArchivePaths = app.paths
    assert paths.quarantines == (QUAR, f"Old years/{QUAR}")
    assert paths.quarantine_for("Old years/2009/a.pdf") == f"Old years/{QUAR}"
    assert paths.quarantine_for("old YEARS/2009/a.pdf") == f"Old years/{QUAR}"
    assert paths.quarantine_for(f"{BANKS}/a.pdf") == QUAR
    assert paths.is_quarantined(f"Old years/{QUAR}/2009/a.pdf")
    assert paths.is_quarantined(f"Old years/{QUAR}")
    assert not paths.is_quarantined(f"Old years/{QUAR}", strict=True)
    assert paths.is_quarantined(f"{QUAR}/x.pdf", strict=True)
    assert not paths.is_quarantined("Old years/2009/a.pdf")
    assert not paths.is_quarantined(f"{BANKS}/{QUAR}/a.pdf")


def test_quarantine_in_extra_folder_stays_on_its_disk(extra_folder, app):
    src = extra_folder.add("2009/a.pdf", b"a", drive_id="x1")
    (extra_folder.root / QUAR).rmdir()  # the fake folder comes with one: made on demand
    app.scan()
    preview = app.browse.quarantine(["x1"], origin="ui", dry_run=True)
    assert [(r.kind, r.dst) for r in preview.done] == [
        (OpKind.MKDIR, f"Old years/{QUAR}"),
        (OpKind.MKDIR, f"Old years/{QUAR}/2009"),
        (OpKind.QUARANTINE, f"Old years/{QUAR}/2009/a.pdf"),
    ]
    assert src.exists()
    result = app.browse.quarantine(["x1"], origin="ui")
    assert result.failed is None and result.error is None
    assert not src.exists()
    assert (extra_folder.root / QUAR / "2009" / "a.pdf").read_bytes() == b"a"
    assert not (app.paths.root / QUAR / "Old years").exists()
    assert app.repo.get("x1").path == f"Old years/{QUAR}/2009/a.pdf"
    rows = journal(app)
    assert [(r["kind"], r["dst"], r["state"]) for r in rows] == [
        ("mkdir", f"Old years/{QUAR}", "done"),
        ("mkdir", f"Old years/{QUAR}/2009", "done"),
        ("quarantine", f"Old years/{QUAR}/2009/a.pdf", "done"),
    ]
    assert {r["batch_id"] for r in rows} == {result.batch_id}
    undone = app.activity.undo(result.batch_id)
    assert undone.batch.failed is None and undone.batch.error is None
    assert src.read_bytes() == b"a"


def test_to_delete_waiting_lists_all_folders(extra_folder, app, fake_archive):
    fake_archive.add(f"{BANKS}/m.pdf", b"m" * 10, drive_id="id-m")
    extra_folder.add("2009/a.pdf", b"a" * 20, drive_id="x1")
    app.scan()
    for drive_id in ("id-m", "x1"):
        result = app.browse.quarantine([drive_id], origin="ui")
        assert result.failed is None and result.error is None
    long_ago = time.time() - 40 * 86400
    with app.engine.begin() as conn:
        conn.execute(
            operations.update()
            .where(operations.c.dst == f"Old years/{QUAR}/2009/a.pdf")
            .values(finished=long_ago)
        )
    result = _waiting(app, 30)
    assert [(f.path, f.days, f.approximate) for f in result.items] == [
        (f"Old years/{QUAR}/2009/a.pdf", 40, False)
    ]
    assert (result.in_to_delete, result.in_to_delete_size) == (2, 30)
    assert {f.path for f in _waiting(app, 0).items} == {
        f"{QUAR}/{BANKS}/m.pdf",
        f"Old years/{QUAR}/2009/a.pdf",
    }


def test_moving_into_an_extra_to_delete_is_refused(extra_folder, app, fake_archive):
    fake_archive.add(f"{BANKS}/m.pdf", b"m", drive_id="id-m")
    extra_folder.add(f"{QUAR}/keep.txt", b"k")
    app.scan()
    with pytest.raises(InvalidRequest):
        app.browse.move(["id-m"], f"Old years/{QUAR}", origin="ui", dry_run=True)
    assert (fake_archive.root / BANKS / "m.pdf").exists()


def _waiting(app, days):
    job = app.maintenance.start("waiting", days)
    job.join(15)
    view = job.view()
    assert view.state == "done", (view.state, view.error)
    return view.result
