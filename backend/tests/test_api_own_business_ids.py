"""Your own business IDs: PUT /api/identifier-names/own. They name no sender, link no
files in Relatives and do not count for ``id:*``; Found in this document says "yours"."""

import yaml

from dam import packs
from test_api import LOCAL_ORIGIN, make_client
from test_api_identifier_names import YT, _bills, _put


def _own(c, own, kind="fi.ytunnus", value=YT):
    return c.put(
        "/api/identifier-names/own",
        json={"kind": kind, "value": value, "own": own},
        headers=LOCAL_ORIGIN,
    )


def test_marking_your_own_id_saves_it_and_shows_it(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        done = _own(c, True)
        assert done.status_code == 200 and done.json() == {"changed": 0, "own": True}
        assert app.settings.own_business_ids == [YT]
        assert packs.active().own_ids == {YT}
        settings_file = app.app_paths.config_dir / "settings.yaml"
        saved = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
        assert saved["own_business_ids"] == [YT]
        found = c.get("/api/files/b0/identifiers").json()["identifiers"]
        assert [(i["value"], i["own"]) for i in found] == [(YT, True)]
        row = c.get("/api/identifier-names").json()["names"][0]
        assert (row["value"], row["own"]) == (YT, True)
        assert _own(c, False).json() == {"changed": 0, "own": False}
        assert app.settings.own_business_ids == [] and packs.active().own_ids == frozenset()
        assert c.get("/api/files/b0/identifiers").json()["identifiers"][0]["own"] is False


def test_your_own_id_gives_no_sender_and_unmarking_gives_it_back(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        _put(c, {"kind": "fi.ytunnus", "value": YT, "name": "Vesi Oy"})
        assert _own(c, True).json() == {"changed": 3, "own": True}
        assert c.get("/api/assignments?drive_id=b0").json() == []
        # the name is kept, so it comes back when the ID is not yours after all
        assert _own(c, False).json() == {"changed": 3, "own": False}
        assert c.get("/api/assignments?drive_id=b0").json()[0]["sender"] == "Vesi Oy"


def test_your_own_id_cannot_be_named(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        _own(c, True)
        got = _put(c, {"kind": "fi.ytunnus", "value": YT, "name": "Me"})
        assert got.status_code == 400 and "yours" in got.json()["error"]


def test_marking_twice_keeps_one(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        _own(c, True)
        _own(c, True)
        assert app.settings.own_business_ids == [YT]


def test_only_a_valid_business_id_can_be_yours(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        assert _own(c, True, kind="core.iban", value="FI2112345600000785").status_code == 400
        assert _own(c, True, kind="core.domain", value="vesi.fi").status_code == 400
        assert _own(c, True, value="0112038-8").status_code == 400  # in no document
        assert _own(c, False, value="0112038-8").json() == {"changed": 0, "own": False}


def test_marking_takes_back_a_sender_its_name_gave_a_parked_file(app, fake_archive):
    from sqlalchemy import select

    from dam.db.tables import file_assignments

    _bills(app, fake_archive)
    with make_client(app) as c:
        _put(c, {"kind": "fi.ytunnus", "value": YT, "name": "Vesi Oy"})
        app.repo.park("10. Bills/b2.pdf")
        _own(c, True)
    with app.engine.connect() as conn:
        assert conn.execute(select(file_assignments.c.sender)).scalars().all() == []


def test_not_mine_works_with_the_country_off(app, fake_archive):
    _bills(app, fake_archive)
    with make_client(app) as c:
        _own(c, True)
        packs.activate(packs.build([], ["en"], app.settings.own_business_ids))
        app._packs = packs.active()
        assert _own(c, False).json() == {"changed": 0, "own": False}
        assert app.settings.own_business_ids == []
