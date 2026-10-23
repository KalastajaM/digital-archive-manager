"""Files in a filing code's inbox folder (``<inbox>/To pay/``) are inbox files."""

from datetime import date

from fastapi.testclient import TestClient

from dam.ai.tasks.suggest_filing import recent_filings
from dam.api import create_api
from dam.config import SpecialFolders
from test_ai_tasks import journal_move
from test_api import BASE, LOCAL_ORIGIN

INBOX = SpecialFolders().inbox


def listed(app) -> list[str]:
    return [e.record.drive_id for e in app.inbox.list()]


def test_code_folder_file_is_inbox(app, fake_archive):
    fake_archive.add(f"{INBOX}/To pay/bill.pdf", drive_id="b1")
    app.scan()
    assert listed(app) == ["b1"]
    assert app.repo.counts()["inbox"] == 1
    path = f"{INBOX}/To pay/bill.pdf"
    assert app.repo.in_inbox_path(path)
    assert app.repo.inbox_code_of(path) == "P"
    assert app.repo.inbox_code_of(f"{INBOX}/bill.pdf") is None
    assert [r.drive_id for r in app.repo.inbox_files()] == ["b1"]


def test_files_directly_in_the_inbox_have_no_code(app, fake_archive):
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="s1")
    fake_archive.add(f"{INBOX}/To pay/bill.pdf", drive_id="b1")
    app.scan()
    assert sorted(listed(app)) == ["b1", "s1"]
    assert app.repo.counts()["inbox"] == 2
    assert app.repo.inbox_code_of(f"{INBOX}/scan.pdf") is None


def test_own_subfolder_is_not_inbox(app, fake_archive):
    fake_archive.add(f"{INBOX}/Old stuff/x.pdf", drive_id="x1")
    app.scan()
    assert listed(app) == []
    assert app.repo.counts()["inbox"] == 0
    assert not app.repo.in_inbox_path(f"{INBOX}/Old stuff/x.pdf")
    assert app.repo.inbox_code_of(f"{INBOX}/Old stuff/x.pdf") is None


def test_deeper_level_is_not_inbox(app, fake_archive):
    fake_archive.add(f"{INBOX}/To pay/2024/x.pdf", drive_id="x1")
    app.scan()
    assert listed(app) == []
    assert app.repo.counts()["inbox"] == 0
    assert app.repo.inbox_code_of(f"{INBOX}/To pay/2024/x.pdf") is None


def test_code_folder_elsewhere_is_not_inbox(app, fake_archive):
    fake_archive.add("10. Financial/To pay/x.pdf", drive_id="x1")
    app.scan()
    assert listed(app) == []
    assert app.repo.counts()["inbox"] == 0
    assert app.repo.inbox_code_of("10. Financial/To pay/x.pdf") is None


def test_code_folder_matches_folded(app, fake_archive):
    fake_archive.add(f"{INBOX}/to PAY/bill.pdf", drive_id="b1")
    app.scan()
    assert listed(app) == ["b1"]
    assert app.repo.counts()["inbox"] == 1
    assert app.repo.inbox_code_of(f"{INBOX}/to PAY/bill.pdf") == "P"


def test_inbox_itself_matches_folded(app):
    assert app.repo.in_inbox_path(f"{INBOX.upper()}/x.pdf")
    assert app.repo.inbox_code_of(f"{INBOX.lower()}/TO PAY/x.pdf") == "P"


def test_removed_code_folder_files_leave_inbox(app, fake_archive):
    disk = fake_archive.add(f"{INBOX}/To pay/bill.pdf", drive_id="b1")
    app.scan()
    assert listed(app) == ["b1"]
    app.save_codes([c for c in app.codes if c.code != "P"])
    assert listed(app) == []
    assert app.repo.counts()["inbox"] == 0
    assert app.repo.inbox_code_of(f"{INBOX}/To pay/bill.pdf") is None
    assert disk.is_file()
    assert app.repo.get("b1").path == f"{INBOX}/To pay/bill.pdf"


def test_code_folders_survive_a_transaction(app):
    with app.repo.transaction() as bound:
        assert bound.code_folders == app.repo.code_folders
        assert bound.inbox_code_of(f"{INBOX}/To pay/x.pdf") == "P"


def test_collection_and_item_in_inbox_flags(app, fake_archive):
    fake_archive.add(f"{INBOX}/To pay/bill.pdf", drive_id="b1")
    fake_archive.add(f"{INBOX}/Old stuff/x.pdf", drive_id="x1")
    app.scan()
    with TestClient(create_api(app), base_url=BASE) as client:

        def post(url, body):
            r = client.post(url, json=body, headers=LOCAL_ORIGIN)
            assert r.status_code == 200, r.text
            return r.json()

        item = post("/api/items", {"tray": "to-pay", "drive_ids": ["b1", "x1"]})
        files = client.get(f"/api/items/{item['id']}/files").json()
        assert [(f["drive_id"], f["in_inbox"]) for f in files] == [("b1", True), ("x1", False)]

        cid = post("/api/collections", {"name": "Estate"})["id"]
        post(f"/api/collections/{cid}/members", {"drive_ids": ["b1", "x1"]})
        rows = {r["drive_id"]: r for r in client.get(f"/api/collections/{cid}/attention").json()}
        assert rows["b1"]["in_inbox"] is True
        assert rows["x1"]["in_inbox"] is False
    assert app.today.collection_in_inbox(cid) == 1
    assert app.today.overview(date.today()).inbox == 1


def test_status_inbox_count_includes_code_folders(app, fake_archive):
    fake_archive.add(f"{INBOX}/To pay/bill.pdf", drive_id="b1")
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="s1")
    app.scan()
    with TestClient(create_api(app), base_url=BASE) as client:
        assert client.get("/api/status").json()["inbox_count"] == 2


def test_filing_examples_include_moves_out_of_a_code_folder(app):
    journal_move(app, f"{INBOX}/To pay/bill.pdf", "10. Financial/Banks/bill.pdf", at=1000.0)
    journal_move(app, f"{INBOX}/Old stuff/x.pdf", "20. Home/x.pdf", at=1001.0)
    journal_move(app, f"{INBOX}/To pay/2024/y.pdf", "20. Home/y.pdf", at=1002.0)
    journal_move(app, f"{INBOX}/scan.pdf", "20. Home/scan.pdf", at=1003.0)
    assert recent_filings(app) == [("scan.pdf", "20. Home"), ("bill.pdf", "10. Financial/Banks")]
