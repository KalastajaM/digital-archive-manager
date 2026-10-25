"""Search filters (``dam.query``) against the index: each filter, quotes, negation,
combinations, and the API. Fake archives only."""

import os
from datetime import datetime

import pytest

from dam.config import Person
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from test_api import make_client

MEDICAL = "50. Medical"
OTHERS = "90. Other People"

# drive id -> path
FILES = {
    "kela": f"{MEDICAL}/20261003_Kela decision.pdf",
    "doc": f"{MEDICAL}/Referral letter.docx",
    "xray": f"{MEDICAL}/Hospital/xray.PNG",
    "tax": "10. Financial/Taxes/2025_tax return.pdf",
    "bill": "10. Financial/Bills/20260112_Northpower.pdf",
    "sheet": "10. Financial/budget.xlsx",
    "sale1": "20. House/sale contract.pdf",
    "sale2": "20. House/Photos/front.jpg",
    "other": f"{OTHERS}/Aunt Lisa kela.pdf",
}


@pytest.fixture
def archive(app, fake_archive):
    app.settings.people = [
        Person(name="Tiina", match=["Tiina"]),
        Person(name="Michiel", match=["Michiel Visser"]),
    ]
    for drive_id, rel in FILES.items():
        fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    # a file with no date in its name is dated by the time it was last modified
    for drive_id, rel in FILES.items():
        when = datetime(2024, 5, 17, 12) if drive_id == "doc" else datetime(2023, 3, 3, 12)
        os.utime(fake_archive.root / rel, (0, when.timestamp()))
    scan(app.paths, app.repo)
    for drive_id in FILES:
        text = "Kela decision about reimbursement" if drive_id in ("kela", "other") else "plain"
        app.repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText(text, "test"), "indexed")
    return app


def ids(app, q, **kw):
    return sorted(h.drive_id for h in app.search(q, limit=100, **kw))


def test_a_filter_with_no_words_lists_files_by_name(archive):
    hits = archive.search("type:pdf", limit=100)
    names = [h.name for h in hits]
    assert names == sorted(names, key=str.lower)
    assert sorted(h.drive_id for h in hits) == ["bill", "kela", "other", "sale1", "tax"]


def test_name_matches_the_file_name_only(archive):
    # "kela" is in the text of both Kela files, the name filter only sees names
    assert ids(archive, "name:kela") == ["kela", "other"]
    assert ids(archive, "name:*northpower*") == ["bill"]
    assert ids(archive, "name:2026*") == ["bill", "kela"]  # anchored at the start
    assert ids(archive, "name:sale?contract.pdf") == ["sale1"]
    assert ids(archive, "name:*.png") == ["xray"]  # the case of the name is ignored
    assert ids(archive, "name:reimbursement") == []  # text is not the name


def test_name_wildcard_characters_of_sql_are_literal(archive):
    assert ids(archive, "name:50%") == []
    assert ids(archive, "name:sale_contract") == []


def test_in_a_folder_and_below(archive):
    assert ids(archive, f'in:"{MEDICAL}"') == ["doc", "kela", "xray"]
    assert ids(archive, f'in:"{MEDICAL}/Hospital"') == ["xray"]
    assert ids(archive, "in:20. House") == []  # an unquoted value stops at the space
    assert ids(archive, 'in:"10. Financial"') == ["bill", "sheet", "tax"]
    # a longer name is not "below" a shorter one
    assert ids(archive, "in:10. Fin") == []


def test_in_is_not_fooled_by_like_characters(archive):
    assert ids(archive, 'in:"50_ Medical"') == []


def test_tag_filter_and_the_tag_parameter_agree(archive):
    archive.tags.add("kela", ["insurance", "Medical"])
    archive.tags.add("doc", ["medical"])
    assert ids(archive, "tag:insurance") == ["kela"]
    assert ids(archive, "tag:MEDICAL") == ["doc", "kela"]
    assert ids(archive, "tag:medical tag:insurance") == ["kela"]
    assert ids(archive, "", tags=["insurance"]) == ["kela"]
    assert ids(archive, "tag:medical", tags=["insurance"]) == ["kela"]
    assert ids(archive, "tag:nothing") == []


def test_tag_mode_any_applies_to_tag_filters(archive):
    archive.tags.add("kela", ["insurance"])
    archive.tags.add("doc", ["medical"])
    assert ids(archive, "tag:insurance tag:medical") == []
    assert ids(archive, "tag:insurance tag:medical", tag_mode="any") == ["doc", "kela"]
    assert ids(archive, "tag:insurance tag:nope", tag_mode="any") == ["kela"]


def test_negated_tag(archive):
    archive.tags.add("kela", ["paid"])
    archive.tags.add("bill", ["paid"])
    assert ids(archive, f'in:"{MEDICAL}" -tag:paid') == ["doc", "xray"]
    assert ids(archive, "type:pdf -tag:paid -tag:unknown") == ["other", "sale1", "tax"]


def test_collection_and_nested_collections(archive):
    house = archive.collections.create("House sale")
    photos = archive.collections.create("Photos", parent_id=house.id)
    archive.collections.add_members(house.id, ["sale1"])
    archive.collections.add_members(photos.id, ["sale2"])
    assert ids(archive, 'collection:"House sale"') == ["sale1", "sale2"]  # nested ones count
    assert ids(archive, "collection:photos") == ["sale2"]
    assert ids(archive, 'collection:"house SALE" type:image') == ["sale2"]
    assert ids(archive, "collection:nope") == []
    assert "sale1" not in ids(archive, '-collection:"House sale" type:pdf')


def test_collection_with_a_member_folder_includes_what_is_inside(archive):
    folder = archive.repo.by_path(f"{MEDICAL}/Hospital")
    col = archive.collections.create("Hospital stuff")
    archive.collections.add_members(col.id, [folder.drive_id])
    assert ids(archive, 'collection:"Hospital stuff"') == ["xray"]


def test_from_and_for(archive):
    archive.assignments.set(["kela", "doc"], sender="Kela (Social Insurance)", person="Tiina")
    archive.assignments.set(["bill"], sender="Northpower", person="Michiel")
    assert ids(archive, "from:kela") == ["doc", "kela"]  # contains, case ignored
    assert ids(archive, "from:Northpower") == ["bill"]
    assert ids(archive, "for:tiina") == ["doc", "kela"]
    assert ids(archive, "for:Tiina from:northpower") == []
    assert ids(archive, "for:nobody") == []
    assert ids(archive, "type:pdf -for:Tiina") == ["bill", "other", "sale1", "tax"]


def test_type_by_extension_and_group(archive):
    assert ids(archive, "type:pdf") == ["bill", "kela", "other", "sale1", "tax"]
    assert ids(archive, "type:image") == ["sale2", "xray"]
    assert ids(archive, "type:.PNG") == ["xray"]
    assert ids(archive, "type:doc") == ["doc"]
    assert ids(archive, "type:sheet") == ["sheet"]
    assert ids(archive, "type:zzz") == []


def test_dates_come_from_the_name_else_the_modified_time(archive):
    assert ids(archive, "date:2026") == ["bill", "kela"]
    assert ids(archive, "date:2026-10") == ["kela"]
    assert ids(archive, "date:2026-10-03") == ["kela"]
    assert ids(archive, "date:2026-10-04") == []
    assert ids(archive, "date:2024-05") == ["doc"]  # no date in the name: its mtime
    assert ids(archive, "date:2024-05-17") == ["doc"]


def test_before_and_after_include_the_first_day_of_the_period(archive):
    assert "kela" in ids(archive, "after:2026-10")
    assert "bill" not in ids(archive, "after:2026-10")
    assert "kela" in ids(archive, "after:2026-10-03")
    assert "kela" not in ids(archive, "after:2026-10-04")
    assert ids(archive, "date:2026 before:2026-02") == ["bill"]
    assert ids(archive, "after:2026-01 before:2026-11 date:2026") == ["bill", "kela"]
    assert "tax" not in ids(archive, "after:2025")  # modified in 2023, no date in the name
    assert "doc" in ids(archive, "after:2024")
    assert "bill" not in ids(archive, "before:2026-01-12")
    assert "bill" in ids(archive, "before:2026-01-13")


def test_negated_date(archive):
    assert "bill" not in ids(archive, "-date:2026")
    assert "tax" in ids(archive, "-date:2026")


def test_tray_by_id_or_name_open_items_only(archive):
    archive.trays.create_quick("to-pay", ["bill", "tax"])
    archive.trays.create_quick("to-read", ["doc"])
    assert ids(archive, "tray:to-pay") == ["bill", "tax"]
    assert ids(archive, 'tray:"To pay"') == ["bill", "tax"]
    assert ids(archive, "tray:TO-READ") == ["doc"]
    assert ids(archive, "tray:nope") == []
    assert ids(archive, "type:pdf -tray:to-pay") == ["kela", "other", "sale1"]


def test_is_starred_important_locked(archive):
    archive.marks.star(["kela"])
    archive.marks.mark_important(["bill"])
    folder = archive.repo.by_path(f"{MEDICAL}/Hospital")
    archive.marks.mark_important([folder.drive_id])
    archive.locks.lock("tax")
    assert ids(archive, "is:starred") == ["kela"]
    assert ids(archive, "is:important") == ["bill", "xray"]  # a marked folder covers its files
    # only the owner's own locks; Important files (always locked) are found with is:important
    assert ids(archive, "is:locked") == ["tax"]
    assert ids(archive, "type:pdf -is:locked") == ["bill", "kela", "other", "sale1"]
    assert ids(archive, "is:locked is:important") == []


def test_is_todo_note_summary(archive):
    archive.notes.add_check("file", "kela", "Call them")
    done = archive.notes.add_check("file", "doc", "Done already")
    archive.notes.set_check(done.id, done=True)
    archive.trays.create_quick("to-pay", ["bill"])
    item = archive.trays.for_file("bill")[0]
    archive.notes.add_check("item", str(item.id), "Pay it")
    archive.notes.set("file", "tax", "Check with accountant")
    archive.notes.set("file", "sale1", "   ")
    archive.summaries.put("sale1", "user", "The contract of sale.")
    assert ids(archive, "is:todo") == ["bill", "kela"]
    assert ids(archive, "is:note") == ["tax"]
    assert ids(archive, "is:summary") == ["sale1"]
    assert ids(archive, "type:pdf -is:todo -is:note -is:summary") == ["other"]


def test_filters_combine_with_each_other_and_with_words(archive):
    archive.tags.add("kela", ["insurance"])
    archive.tags.add("other", ["insurance"])
    assert ids(archive, "kela") == ["kela", "other"]  # words: the text, as before
    assert ids(archive, f'kela in:"{MEDICAL}"') == ["kela"]
    assert ids(archive, f'kela -in:"{OTHERS}"') == ["kela"]
    assert ids(archive, "kela tag:insurance type:pdf date:2026") == ["kela"]
    assert ids(archive, "reimbursement name:*decision*") == ["kela"]
    assert ids(archive, "reimbursement name:*lisa*") == ["other"]
    assert ids(archive, "reimbursement name:*nothing*") == []


def test_words_hits_keep_a_snippet_and_rank(archive):
    (hit,) = archive.search(f'reimbursement in:"{MEDICAL}"')
    assert hit.drive_id == "kela" and "[" in hit.snippet


def test_folder_parameter_still_limits(archive):
    assert ids(archive, "type:pdf", folder=MEDICAL) == ["kela"]


def test_unknown_filter_names_search_as_words(archive):
    assert ids(archive, "foo:bar") == []
    archive.repo.save_content(
        "sale1", "sha-sale1", ExtractedText("see http://example.org today", "test"), "indexed"
    )
    assert ids(archive, "http:") == ["sale1"]


@pytest.mark.parametrize("q", ["date:2026-13", "is:nope", "after:soon", "tag:", "type:a!b"])
def test_bad_values_are_a_400(archive, q):
    with make_client(archive) as c:
        r = c.get("/api/search", params={"q": q})
    assert r.status_code == 400, r.text
    assert r.json()["error"]


def test_the_api_takes_the_whole_query_in_q(archive):
    archive.tags.add("kela", ["insurance"])
    with make_client(archive) as c:
        r = c.get("/api/search", params={"q": f'kela in:"{MEDICAL}" tag:insurance -type:docx'})
        assert r.status_code == 200, r.text
        assert [h["drive_id"] for h in r.json()] == ["kela"]
        # the old tag parameters keep working beside it
        r = c.get("/api/search", params=[("q", "type:pdf"), ("tag", "insurance")])
        assert [h["drive_id"] for h in r.json()] == ["kela"]
        assert c.get("/api/search", params={"q": ""}).json() == []
        assert c.get("/api/search", params={"q": "-tag:x"}).json() != []  # only a negation lists


def test_only_a_negation_lists_every_other_file(archive):
    archive.tags.add("kela", ["paid"])
    assert "kela" not in ids(archive, "-tag:paid")
    assert len(ids(archive, "-tag:paid")) == len(FILES) - 1
