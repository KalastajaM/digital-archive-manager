import unicodedata

from dam.extract.base import ExtractedText
from dam.index.repo import FileRecord, FileRepo
from dam.search import search


def add(repo: FileRepo, drive_id: str, path: str, body: str = "", **kw) -> None:
    repo.upsert(FileRecord(drive_id=drive_id, path=path, **kw))
    repo.save_content(drive_id, None, ExtractedText(body, "test") if body else None, "indexed")


def test_finds_by_text(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/one.pdf", "The invoice for the heating oil delivery")
    add(repo, "d2", "a/two.pdf", "Nothing relevant here")
    hits = search(engine, "heating")
    assert [h.drive_id for h in hits] == ["d1"]
    assert hits[0].path == "a/one.pdf" and hits[0].name == "one.pdf"
    assert "[heating]" in hits[0].snippet
    assert isinstance(hits[0].rank, float)


def test_finds_by_name_prefix(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/Apteekki kuitti.pdf")
    hits = search(engine, "apte")
    assert [h.drive_id for h in hits] == ["d1"]
    assert hits[0].snippet == "Apteekki kuitti.pdf"


def test_diacritics_insensitive(engine):
    nfd = unicodedata.normalize("NFD", "Kyynärpää.pdf")
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", f"a/{nfd}", "kirje")
    hits = search(engine, "kyynarpaa")
    assert [h.drive_id for h in hits] == ["d1"]
    assert hits[0].name == nfd and hits[0].path == f"a/{nfd}"
    nfd_query = unicodedata.normalize("NFD", "Kyynärpää")
    assert [h.drive_id for h in search(engine, nfd_query)] == ["d1"]


def test_folder_filter(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "11. Bills & Receipts/a.pdf", "electricity")
    add(repo, "d2", "11. Bills & Receipts/sub/b.pdf", "electricity")
    add(repo, "d3", "11. Bills & Receipts 2/c.pdf", "electricity")
    add(repo, "d4", "other/d.pdf", "electricity")
    got = {h.drive_id for h in search(engine, "electricity", folder="11. Bills & Receipts")}
    assert got == {"d1", "d2"}
    assert {h.drive_id for h in search(engine, "electricity")} == {"d1", "d2", "d3", "d4"}


def test_folder_filter_escapes_like_wildcards(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a_b/x.pdf", "word")
    add(repo, "d2", "axb/x.pdf", "word")
    assert {h.drive_id for h in search(engine, "word", folder="a_b")} == {"d1"}


def test_special_chars_do_not_crash(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/foo.pdf", "foo and more")
    assert [h.drive_id for h in search(engine, '"foo" AND (')] == ["d1"]
    assert [h.drive_id for h in search(engine, '"foo')] == ["d1"]
    assert search(engine, "a\x00b") == []
    assert [h.drive_id for h in search(engine, "fo\x00o")] == []
    search(engine, "* ^ - : NEAR(")
    assert search(engine, "- *") == []
    assert search(engine, "   ") == []
    assert search(engine, "") == []


def test_missing_and_parked_excluded(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/live.pdf", "needle")
    add(repo, "d2", "a/gone.pdf", "needle", missing=True)
    add(repo, "d3", "a/moved.pdf", "needle")
    repo.park("a/moved.pdf")
    assert [h.drive_id for h in search(engine, "needle")] == ["d1"]


def test_limit(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    for i in range(5):
        add(repo, f"d{i}", f"a/{i}.pdf", "needle")
    assert len(search(engine, "needle", limit=3)) == 3


def test_punctuation_only_tokens_dropped(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/x.pdf", "foo bar")
    assert [h.drive_id for h in search(engine, "foo ba -")] == ["d1"]
    assert [h.drive_id for h in search(engine, "ba -")] == ["d1"]


def test_literal_bracket_in_body_does_not_fake_match(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/Needle.pdf", "[ref] unrelated text")
    hits = search(engine, "needle")
    assert [h.drive_id for h in hits] == ["d1"]
    assert hits[0].snippet == "Needle.pdf"


def test_folder_root_means_no_filter(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/x.pdf", "word")
    add(repo, "d2", "b/y.pdf", "word")
    for f in ("/", "", None):
        assert {h.drive_id for h in search(engine, "word", folder=f)} == {"d1", "d2"}


def test_ties_ordered_by_path(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    for i in (3, 1, 2):
        add(repo, f"d{i}", f"a/{i}.pdf", "needle")
    assert [h.path for h in search(engine, "needle")] == ["a/1.pdf", "a/2.pdf", "a/3.pdf"]


def test_snippet_collapses_whitespace_and_control_characters(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(
        repo,
        "d1",
        "a/p.pdf",
        "SPORTTITURVAN\r\nYksilöllinen\x0c vakuutus\x00ehdot\tosa\n\n[x] tail",
    )
    hit = search(engine, "vakuutus")[0]
    assert "[vakuutus]" in hit.snippet
    assert not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in hit.snippet)
    assert "  " not in hit.snippet


def test_snippet_drops_noncharacters_inside_words(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/p.pdf", "urheilulisenssiva\ufffekuutuksessa ja va\u00adkuutus\u200b ehdot")
    hit = search(engine, "ehdot")[0]
    assert "urheilulisenssivakuutuksessa ja vakuutus [ehdot]" in hit.snippet


def _three(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    add(repo, "d1", "a/one.pdf", "Kela decision about the annual report")
    add(repo, "d2", "a/two.pdf", "Kelan lasku, report annual")
    add(repo, "d3", "a/three.pdf", "If insurance draft")


def found(engine, q):
    return sorted(h.drive_id for h in search(engine, q))


def test_dash_and_not_leave_words_out(engine):
    _three(engine)
    assert found(engine, "annual -lasku") == ["d1"]
    assert found(engine, "annual NOT lasku") == ["d1"]
    assert found(engine, '-"annual report" pdf') == ["d2", "d3"]  # names count as text
    assert found(engine, "-draft") == ["d1", "d2"]  # only exclusions: every other file


def test_or_wants_either(engine):
    _three(engine)
    assert found(engine, "kela OR insurance") == ["d1", "d3"]
    assert found(engine, "annual kela OR kelan") == ["d1", "d2"]
    assert found(engine, "kela AND decision") == ["d1"]


def test_a_phrase_wants_the_words_in_order(engine):
    _three(engine)
    assert found(engine, '"annual report"') == ["d1"]
    assert found(engine, "annual report") == ["d1", "d2"]


def test_a_star_is_a_prefix_anywhere(engine):
    _three(engine)
    assert found(engine, "kela* annual") == ["d1", "d2"]
    assert found(engine, "kela annual") == ["d1"]
