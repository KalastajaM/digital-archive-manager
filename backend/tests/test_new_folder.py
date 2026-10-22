"""New folder lists the folder in the index at once; undo takes it out again."""

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api

BANKS = "10. Financial/Banks"
BASE = "http://127.0.0.1:8765"
ORIGIN = {"Origin": BASE}


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def test_a_new_folder_is_listed_at_once_and_gone_again_after_undo(app, fake_archive):
    app.scan()
    batch = app.layout.new_folder(BANKS, "Taxes")
    assert batch.failed is None and (fake_archive.root / BANKS / "Taxes").is_dir()
    assert f"{BANKS}/Taxes" in app.browse.folders()
    assert "Taxes" in [e.name for e in app.browse.list_dir(BANKS)]
    app.activity.undo(batch.batch_id)
    assert not (fake_archive.root / BANKS / "Taxes").exists()
    assert f"{BANKS}/Taxes" not in app.browse.folders()
    assert "Taxes" not in [e.name for e in app.browse.list_dir(BANKS)]


def test_api_new_folder_is_listed_at_once(client, app):
    app.scan()
    r = client.post("/api/folders/new", json={"parent": BANKS, "name": "Taxes"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["done"][0]["dst"] == f"{BANKS}/Taxes"
    assert f"{BANKS}/Taxes" in client.get("/api/folders").json()
    assert "Taxes" in [e["name"] for e in client.get("/api/browse", params={"path": BANKS}).json()]
