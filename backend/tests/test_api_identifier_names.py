"""Settings, Senders: GET and PUT /api/identifier-names."""

from dam import countries, packs
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from test_api import LOCAL_ORIGIN, make_client

YT = "0112038-9"


def _bills(app, fake_archive, n=3):
    ids = [f"b{i}" for i in range(n)]
    for drive_id in ids:
        fake_archive.add(f"10. Bills/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    sig = countries.signature()
    for drive_id in ids:
        app.repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText("bill", "t"), "indexed")
        app.repo.save_identifiers(
            drive_id, f"sha-{drive_id}", sig, [("fi.ytunnus", YT)], {("fi.ytunnus", YT): "Vesi Oy"}
        )
    return ids


def _put(c, body):
    return c.put("/api/identifier-names", json=body, headers=LOCAL_ORIGIN)


def test_the_list_and_a_confirmed_name(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        got = c.get("/api/identifier-names").json()
        assert got == {
            "names": [
                {
                    "kind": "fi.ytunnus",
                    "label": "Business ID (Y-tunnus)",
                    "value": YT,
                    "files": 3,
                    "suggested": "Vesi Oy",
                    "name": None,
                    "set_at": None,
                    "filled": 0,
                    "own": False,
                }
            ]
        }
        done = _put(c, {"kind": "fi.ytunnus", "value": YT, "name": "Vesi Oy"})
        assert done.status_code == 200 and done.json() == {"changed": 3, "name": "Vesi Oy"}
        row = c.get("/api/identifier-names").json()["names"][0]
        assert (row["name"], row["filled"]) == ("Vesi Oy", 3)
        assert c.get("/api/assignments?drive_id=b0").json()[0]["sender"] == "Vesi Oy"
        undone = _put(c, {"kind": "fi.ytunnus", "value": YT, "name": None})
        assert undone.json() == {"changed": 3, "name": None}
        assert c.get("/api/assignments?drive_id=b0").json() == []


def test_a_bad_request_is_400(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        assert _put(c, {"kind": "fi.ytunnus", "value": YT, "name": " "}).status_code == 400
        assert _put(c, {"kind": "core.iban", "value": "x", "name": "A"}).status_code == 400


def test_finland_off_lists_nothing(app, fake_archive):
    _bills(app, fake_archive)
    packs.activate(packs.build([], ["en"]))
    with make_client(app) as c:
        assert c.get("/api/identifier-names").json() == {"names": []}
