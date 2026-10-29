from dam import countries, packs
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from test_api import make_client


def _two_bills(app, fake_archive):
    for drive_id in ("a", "b"):
        fake_archive.add(f"10. Bills/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    sig = countries.signature()
    for drive_id in ("a", "b"):
        app.repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText("bill", "t"), "indexed")
    app.repo.save_identifiers(
        "a", "sha-a", sig, [("fi.ytunnus", "0112038-9"), ("core.domain", "a.fi")]
    )
    app.repo.save_identifiers("b", "sha-b", sig, [("fi.ytunnus", "0112038-9")])


def test_found_in_this_document(app, fake_archive):
    _two_bills(app, fake_archive)
    with make_client(app) as c:
        got = c.get("/api/files/a/identifiers").json()
    assert got == {
        "identifiers": [
            {
                "kind": "fi.ytunnus",
                "label": "Business ID (Y-tunnus)",
                "value": "0112038-9",
                "others": 1,
            },
            {"kind": "core.domain", "label": "Web or mail domain", "value": "a.fi", "others": 0},
        ]
    }


def test_a_country_that_is_off_is_not_shown(app, fake_archive):
    _two_bills(app, fake_archive)
    packs.activate(packs.build([], ["en"]))
    with make_client(app) as c:
        got = c.get("/api/files/a/identifiers").json()
    assert [i["kind"] for i in got["identifiers"]] == ["core.domain"]


def test_an_unknown_file_is_404(app):
    with make_client(app) as c:
        assert c.get("/api/files/nope/identifiers").status_code == 404


def test_status_says_how_far_the_identifiers_pass_is(app, fake_archive):
    _two_bills(app, fake_archive)
    with make_client(app) as c:
        assert c.get("/api/status").json()["identifiers"] == {"read": 2, "total": 2}
