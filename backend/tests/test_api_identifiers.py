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


def test_the_index_summary_says_what_was_found(app, fake_archive):
    _two_bills(app, fake_archive)
    with make_client(app) as c:
        got = c.get("/api/index/summary").json()["identifiers"]
    assert got["found"] == [
        {"label": "business IDs", "count": 2},
        {"label": "IBANs", "count": 0},
        {"label": "web or mail domains", "count": 1},
    ]


def test_page1_with_text_counts_pages_that_have_some(app, fake_archive):
    from dam.extract.layout import Line, Page1Layout

    for drive_id in ("p", "q"):
        fake_archive.add(f"10. Bills/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    for drive_id in ("p", "q"):
        app.repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText("x", "t"), "indexed")
    line = Line(text="Vesilaitos Oy", box=(0.1, 0.1, 0.5, 0.12))
    app.repo.save_layout("p", "sha-p", Page1Layout(lines=[line]))
    app.repo.save_layout("q", "sha-q", Page1Layout(lines=[]))  # read: no text on page 1
    with make_client(app) as c:
        page1 = c.get("/api/index/summary").json()["page1"]
    assert (page1["read"], page1["total"], page1["with_text"]) == (2, 2, 1)
