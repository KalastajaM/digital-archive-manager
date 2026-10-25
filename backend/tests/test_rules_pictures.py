"""Picture areas: the zone in the model, the matching of a crop against page 1 (shift, scale,
brightness, noise, a small skew; not another shape), the checks, the replay with scores and
the explanation."""

import shutil
import time

import pytest
import yaml
from PIL import Image

import synth
from dam.extract.base import ExtractedText
from dam.extract.picture import page_picture, write_picture
from dam.index.repo import FileRecord
from dam.rules.engine import check, suggest
from dam.rules.learned import write_rules_file
from dam.rules.model import Rule, load_rules
from dam.rules.picture import (
    DEFAULT_MIN_SCORE,
    PictureError,
    Pictures,
    Template,
    check_image_path,
    crop_file,
    cut_crop,
    load_page,
    match,
    png_bytes,
)
from dam.rules.replay import explain, replay
from test_rules_zone import INBOX, add, layout

BOX = synth.LOGO_BOX


def crop_of(img=None) -> Image.Image:
    return cut_crop(page_picture(img or synth.letter()), BOX)


def score_of(img: Image.Image, tmp_path, crop=None, box=BOX) -> float:
    path = tmp_path / "page.jpg"
    page_picture(img).save(path, "JPEG", quality=70)
    return match(Template(crop or crop_of(), box), load_page(path)).score


# --- the model ------------------------------------------------------------------------


def picture_zone(**extra):
    return {"box": list(BOX), "image": "areas/x-1.png", **extra}


@pytest.mark.parametrize(
    "image",
    [
        "areas/../x.png",
        "../areas/x.png",
        "/etc/passwd",
        "areas/sub/x.png",
        "areas\\x.png",
        "areas/x.jpg",
        "areas/.x.png",
        "other/x.png",
        "x.png",
        "areas/",
        "areas/x..png",
        "C:/areas/x.png",
    ],
)
def test_a_picture_path_must_stay_inside_the_areas_folder(image):
    with pytest.raises(ValueError):
        check_image_path(image)
    with pytest.raises(ValueError):
        Rule.model_validate({"id": "x", "when": {"zones": [{"box": list(BOX), "image": image}]}})


def test_crop_file_stays_inside_the_rules_areas_folder(tmp_path):
    (tmp_path / "areas").mkdir()
    assert crop_file(tmp_path, "areas/a-1.png") == (tmp_path / "areas" / "a-1.png").resolve()
    with pytest.raises(PictureError):
        crop_file(tmp_path, "areas/../a.png")


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="needs symlinks")
def test_a_symlink_in_areas_cannot_reach_outside(tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    areas = tmp_path / "rules" / "areas"
    areas.mkdir(parents=True)
    try:
        (areas / "a-1.png").symlink_to(outside)
    except OSError:
        pytest.skip("no symlink privilege")
    with pytest.raises(PictureError):
        crop_file(tmp_path / "rules", "areas/a-1.png")


@pytest.mark.skipif(not hasattr(__import__("os"), "symlink"), reason="needs symlinks")
def test_a_symlinked_areas_folder_cannot_lead_outside_the_rules_folder(tmp_path):
    elsewhere = tmp_path / "archive-ish"
    elsewhere.mkdir()
    (elsewhere / "a-1.png").write_bytes(b"x")
    rules = tmp_path / "rules"
    rules.mkdir()
    try:
        (rules / "areas").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("no symlink privilege")
    with pytest.raises(PictureError):
        crop_file(rules, "areas/a-1.png")
    with pytest.raises(PictureError):
        crop_file(rules, "areas/new.png")


def test_a_picture_zone_has_a_picture_or_words_and_a_valid_min_score():
    rule = Rule.model_validate({"id": "x", "when": {"zones": [picture_zone()]}})
    zone = rule.when.zones[0]
    assert zone.is_picture and zone.threshold == DEFAULT_MIN_SCORE
    assert (
        Rule.model_validate({"id": "x", "when": {"zones": [picture_zone(min_score=0.6)]}})
        .when.zones[0]
        .threshold
        == 0.6
    )
    for bad in (0, -0.1, 1.5):
        with pytest.raises(ValueError, match="min_score"):
            Rule.model_validate({"id": "x", "when": {"zones": [picture_zone(min_score=bad)]}})
    with pytest.raises(ValueError, match="not both"):
        Rule.model_validate({"id": "x", "when": {"zones": [picture_zone(text_contains=["a"])]}})
    with pytest.raises(ValueError, match="min_score is for a picture"):
        Rule.model_validate(
            {
                "id": "x",
                "when": {"zones": [{"box": list(BOX), "text_contains": ["a"], "min_score": 0.5}]},
            }
        )


def test_picture_and_text_zones_round_trip_through_a_rule_file(tmp_path):
    rule = Rule.model_validate(
        {
            "id": "mixed",
            "when": {
                "zones": [
                    {"box": list(BOX), "image": "areas/mixed-1.png", "min_score": 0.8},
                    {"box": [0.5, 0.05, 0.9, 0.1], "text_contains": ["lasku"]},
                    {"box": [0.1, 0.5, 0.4, 0.6], "image": "areas/mixed-2.png"},
                ]
            },
        }
    )
    path = tmp_path / "learned.yaml"
    write_rules_file(path, [rule])
    on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))[0]["when"]["zones"]
    assert on_disk[0] == {"box": list(BOX), "image": "areas/mixed-1.png", "min_score": 0.8}
    assert on_disk[2] == {"box": [0.1, 0.5, 0.4, 0.6], "image": "areas/mixed-2.png"}
    loaded, errors = load_rules(tmp_path)
    assert errors == [] and loaded == [rule]


# --- the matching ---------------------------------------------------------------------


def test_the_same_page_scores_close_to_one_and_reports_where(tmp_path):
    path = tmp_path / "p.jpg"
    page_picture(synth.letter()).save(path, "JPEG", quality=70)
    found = match(Template(crop_of(), BOX), load_page(path))
    assert found.score > 0.97
    x0, y0, x1, y1 = found.box
    assert abs(x0 - BOX[0]) < 0.02 and abs(y0 - BOX[1]) < 0.02
    assert abs((x1 - x0) - (BOX[2] - BOX[0])) < 0.02


@pytest.mark.parametrize(
    "label,img",
    [
        ("shifted", synth.letter(shift=(20, 15))),
        ("shifted the other way", synth.letter(shift=(-30, 18))),
        ("smaller", synth.letter(logo_scale=0.9)),
        ("bigger", synth.letter(logo_scale=1.1)),
        ("darker", synth.brightened(synth.letter(), 0.6)),
        ("noisy", synth.noisy(synth.letter(), 25)),
        ("skewed 2 degrees", synth.skewed(synth.letter(), 2)),
        (
            "all at once",
            synth.skewed(
                synth.noisy(
                    synth.brightened(synth.letter(shift=(10, -8), logo_scale=1.05), 0.8), 15
                ),
                1.5,
            ),
        ),
    ],
)
def test_the_picture_is_found_in_a_rescan(label, img, tmp_path):
    assert score_of(img, tmp_path) >= DEFAULT_MIN_SCORE + 0.05, label


def test_another_shape_in_the_same_place_scores_clearly_lower(tmp_path):
    same = score_of(synth.letter(), tmp_path)
    other = score_of(synth.letter(kind=1), tmp_path)
    assert other < DEFAULT_MIN_SCORE and same - other > 0.2


def test_a_blank_page_and_a_page_of_text_do_not_match(tmp_path):
    assert score_of(Image.new("L", synth.PAGE, 255), tmp_path) == 0.0
    text_only = Image.new("L", synth.PAGE, 255)
    from PIL import ImageDraw

    d = ImageDraw.Draw(text_only)
    for i in range(30):
        d.rectangle((60, 50 + i * 30, 60 + 300 + (i * 37) % 500, 60 + i * 30), fill=90)
    assert score_of(text_only, tmp_path) < DEFAULT_MIN_SCORE


def test_a_flat_crop_scores_zero(tmp_path):
    flat = Image.new("L", (100, 40), 200)
    assert score_of(synth.letter(), tmp_path, crop=flat) == 0.0


def test_the_logo_is_not_found_outside_the_search_window(tmp_path):
    far = synth.letter(shift=(0, 600))  # 600 px lower: well beyond 5 % of the page
    assert score_of(far, tmp_path) < DEFAULT_MIN_SCORE


def test_matching_is_fast(tmp_path):
    path = tmp_path / "p.jpg"
    page_picture(synth.letter()).save(path, "JPEG", quality=70)
    template = Template(crop_of(), BOX)
    match(template, load_page(path))  # warm up
    started = time.perf_counter()
    for _ in range(10):
        match(template, load_page(path))
    per_document = (time.perf_counter() - started) / 10
    assert per_document < 0.25  # about 5 ms here; generous for a slow CI machine


# --- Pictures, the checks ---------------------------------------------------------------


class Setup:
    """A rules folder with one crop and a cache with pictures of two documents."""

    def __init__(self, tmp_path):
        self.rules_dir = tmp_path / "rules"
        self.cache = tmp_path / "cache"
        (self.rules_dir / "areas").mkdir(parents=True)
        (self.rules_dir / "areas" / "acme-1.png").write_bytes(png_bytes(crop_of()))
        self.pictures = Pictures(lambda: self.rules_dir, self.cache)

    def keep(self, drive_id, sha, img):
        write_picture(self.cache, drive_id, sha, page_picture(img))

    def rule(self, extra_zones=(), **when):
        return Rule.model_validate(
            {
                "id": "acme",
                "when": {
                    "zones": [{"box": list(BOX), "image": "areas/acme-1.png"}, *extra_zones],
                    **when,
                },
                "then": {"folder": "Acme"},
            }
        )


@pytest.fixture
def setup(tmp_path):
    return Setup(tmp_path)


def record(drive_id="a", sha="sha-a", path=f"{INBOX}/a.pdf"):
    return FileRecord(drive_id=drive_id, path=path, name="a.pdf", ext="pdf", sha256=sha)


def test_a_rule_with_a_picture_matches_a_page_that_shows_it(setup):
    setup.keep("a", "sha-a", synth.letter(shift=(12, 9)))
    c = check(setup.rule(), record(), "", pictures=setup.pictures)
    assert c.matched and c.picture_score > 0.9
    setup.keep("b", "sha-b", synth.letter(kind=1))
    other = check(setup.rule(), record("b", "sha-b"), "", pictures=setup.pictures)
    assert not other.matched and not other.waiting and other.picture_score < DEFAULT_MIN_SCORE


def test_min_score_decides(setup):
    setup.keep("a", "sha-a", synth.letter(kind=1))
    strict = setup.rule()
    lenient = Rule.model_validate(
        {
            "id": "acme",
            "when": {"zones": [{"box": list(BOX), "image": "areas/acme-1.png", "min_score": 0.5}]},
        }
    )
    assert not check(strict, record(), "", pictures=setup.pictures).matched
    assert check(lenient, record(), "", pictures=setup.pictures).matched


def test_a_document_without_a_picture_is_waiting_not_a_non_match(setup):
    c = check(setup.rule(), record(), "", pictures=setup.pictures)
    assert c.waiting and not c.matched and c.picture_score is None
    # no picture support at all: the same
    assert check(setup.rule(), record(), "").waiting
    # a file that never has a page 1 is not waiting for one
    docx = FileRecord(drive_id="d", path="x/a.docx", name="a.docx", ext="docx", sha256="s")
    assert not check(setup.rule(), docx, "", pictures=setup.pictures).waiting


def test_a_picture_with_a_changed_content_is_not_the_old_picture(setup):
    setup.keep("a", "sha-old", synth.letter())
    assert check(setup.rule(), record(sha="sha-old"), "", pictures=setup.pictures).matched
    # the same file with other content has another sha: no picture for it yet
    assert check(setup.rule(), record(sha="sha-new"), "", pictures=setup.pictures).waiting


def test_text_and_picture_areas_combine_and_text_is_looked_at_first(setup):
    words = {"box": [0.5, 0.05, 0.95, 0.12], "text_contains": ["lasku"]}
    rule = setup.rule([words])
    setup.keep("a", "sha-a", synth.letter())
    page = layout(("Lasku 123", (0.55, 0.06, 0.9, 0.09)))
    assert check(rule, record(), "lasku", layout=page, pictures=setup.pictures).matched
    # the word is not in the text of the document: no match, and the picture is not needed
    no_words = check(rule, record(sha="sha-none"), "other", pictures=setup.pictures)
    assert not no_words.matched and not no_words.waiting
    # the word is there but page 1 is not read yet: waiting
    assert check(rule, record(), "lasku", pictures=setup.pictures).waiting
    # the word is on page 1 but not in the area
    wrong = layout(("Lasku", (0.05, 0.8, 0.3, 0.83)))
    assert not check(rule, record(), "lasku", layout=wrong, pictures=setup.pictures).matched


def test_a_rule_with_only_pictures_needs_no_layout(setup):
    setup.keep("a", "sha-a", synth.letter())
    found = suggest(record(), "", [setup.rule()], layout=None, pictures=setup.pictures)
    assert found.folder == "Acme" and found.waiting_for_page1 is False
    (area,) = found.areas
    assert area.kind == "image" and area.score and area.score > 0.9
    assert area.matched and area.box == BOX and len(area.lines) == 1


def test_a_missing_or_broken_crop_never_matches(setup):
    setup.keep("a", "sha-a", synth.letter())
    gone = Rule.model_validate(
        {"id": "g", "when": {"zones": [{"box": list(BOX), "image": "areas/gone.png"}]}}
    )
    c = check(gone, record(), "", pictures=setup.pictures)
    assert not c.matched and c.picture_score == 0.0
    (setup.rules_dir / "areas" / "bad-1.png").write_bytes(b"not a png")
    bad = Rule.model_validate(
        {"id": "b", "when": {"zones": [{"box": list(BOX), "image": "areas/bad-1.png"}]}}
    )
    assert not check(bad, record(), "", pictures=setup.pictures).matched


def test_a_changed_crop_file_is_picked_up(setup):
    setup.keep("a", "sha-a", synth.letter())
    assert check(setup.rule(), record(), "", pictures=setup.pictures).matched
    other = cut_crop(page_picture(synth.letter(kind=1)), BOX)
    (setup.rules_dir / "areas" / "acme-1.png").write_bytes(png_bytes(other))
    assert not check(setup.rule(), record(), "", pictures=setup.pictures).matched


# --- explain --------------------------------------------------------------------------------


def test_explain_gives_the_picture_area_its_score_and_reason(app, setup):
    special = app.settings.special_folders
    setup.keep("a", "sha-a", synth.letter())
    (hit,) = explain(record(), "", [setup.rule()], special, None, None, None, setup.pictures)
    assert hit.matched and "picture 0.9" in hit.why or "picture 1.0" in hit.why
    (area,) = hit.areas
    assert area.kind == "image" and area.matched and area.reason is None and area.score > 0.9
    setup.keep("b", "sha-b", synth.letter(kind=1))
    (miss,) = explain(
        record("b", "sha-b"), "", [setup.rule()], special, None, None, None, setup.pictures
    )
    assert not miss.matched and "scores 0.7" in miss.why and "needs 0.85" in miss.why
    assert miss.areas[0].reason.startswith("picture 0.7") and miss.areas[0].score < 0.85
    (waiting,) = explain(
        record("c", "sha-c"), "", [setup.rule()], special, None, None, None, setup.pictures
    )
    assert waiting.why == "the picture of page 1 is not made yet"
    assert waiting.areas[0].reason and waiting.areas[0].score is None


# --- the replay ---------------------------------------------------------------------------------


def fill(app, setup, archive, n_match=3, n_other=2):
    for i in range(n_match):
        add(app, archive, f"Insurance/Acme/20250{i + 1}10_A.pdf", f"m{i}", "x")
        setup.keep(f"m{i}", f"sha-m{i}", synth.noisy(synth.letter(shift=(3 * i, 2 * i)), 10 * i))
    for i in range(n_other):
        add(app, archive, f"10. Bank/s{i}.pdf", f"o{i}", "x")
        setup.keep(f"o{i}", f"sha-o{i}", synth.letter(kind=1, shift=(2 * i, 0)))
    add(app, archive, "20. Home/unseen.pdf", "u", "x")  # no picture yet
    add(app, archive, "20. Home/notes.docx", "n", "x")


def run_replay(app, setup, rule, **kw):
    return replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        pictures=setup.pictures,
        **kw,
    )


def test_replay_reports_the_scores_of_matches_and_the_best_non_matches(app, setup, fake_archive):
    fill(app, setup, fake_archive)
    wanted = []
    r = run_replay(app, setup, setup.rule(), want_layouts=wanted.extend)
    assert r.matched == 3
    scores = {s.path: s for s in r.scores}
    assert sum(s.matched for s in r.scores) == 3 and len(r.scores) == 5
    assert all(s.score >= DEFAULT_MIN_SCORE for s in r.scores if s.matched)
    assert all(s.score < DEFAULT_MIN_SCORE for s in r.scores if not s.matched)
    assert scores["10. Bank/s0.pdf"].matched is False
    # the lowest matches come first, then the highest non-matches
    assert [s.matched for s in r.scores] == [True, True, True, False, False]
    # a document without a picture yet is not checked and queued, a .docx is just no match
    assert [(n.path, n.reason) for n in r.not_checked] == [
        ("20. Home/unseen.pdf", "page 1 not read yet")
    ]
    assert wanted == ["u"] and r.reading == 1


def test_replay_scores_are_limited_to_the_two_ends(app, setup, fake_archive):
    for i in range(30):
        add(app, fake_archive, f"Insurance/Acme/doc{i:02}.pdf", f"m{i}", "x")
        setup.keep(f"m{i}", f"sha-m{i}", synth.noisy(synth.letter(), i, seed=i))
    for i in range(15):
        add(app, fake_archive, f"10. Bank/s{i:02}.pdf", f"o{i}", "x")
        setup.keep(f"o{i}", f"sha-o{i}", synth.letter(kind=1, shift=(i, 0)))
    r = run_replay(app, setup, setup.rule())
    assert (r.matched, len(r.scores)) == (30, 30)
    matches = [s.score for s in r.scores if s.matched]
    assert len(matches) == 20 and matches == sorted(matches)
    others = [s.score for s in r.scores if not s.matched]
    assert len(others) == 10 and others == sorted(others, reverse=True)


def test_replay_never_reads_archive_files_for_pictures(app, setup, fake_archive):
    fill(app, setup, fake_archive)
    shutil.rmtree(fake_archive.root)  # the pictures are in the cache: the archive is not needed
    r = run_replay(app, setup, setup.rule())
    assert r.matched == 3 and len(r.scores) == 5


def test_replay_keeps_its_time_budget_with_pictures(app, setup, fake_archive):
    fill(app, setup, fake_archive, n_match=4, n_other=4)
    r = run_replay(app, setup, setup.rule(), budget_s=0.0)
    assert r.truncated and r.checked == 0 and r.total == 10


def test_replay_of_picture_and_text_rule_scores_only_documents_that_pass_the_text(
    app, setup, fake_archive
):
    fill(app, setup, fake_archive)
    app.repo.save_layout("m0", "sha-m0", layout(("Lasku", (0.55, 0.06, 0.9, 0.09))))
    app.repo.save_layout("m1", "sha-m1", layout(("Other", (0.55, 0.06, 0.9, 0.09))))
    for i in (0, 1, 2):  # the word is in the text of these three documents
        app.repo.save_content(f"m{i}", f"sha-m{i}", ExtractedText("lasku", "t"), "indexed")
    rule = setup.rule([{"box": [0.5, 0.05, 0.95, 0.12], "text_contains": ["lasku"]}])
    r = run_replay(app, setup, rule)
    assert r.matched == 1  # m0: the word is in the area and the picture shows
    assert [s.path for s in r.scores] == ["Insurance/Acme/20250110_A.pdf"]
    assert [n.path for n in r.not_checked] == ["Insurance/Acme/20250310_A.pdf"]  # m2: no layout


def test_a_rule_without_picture_areas_never_touches_the_picture_machinery(app, setup, fake_archive):
    add(app, fake_archive, "10. Bank/a.pdf", "a", "pohjola")
    rule = Rule.model_validate({"id": "p", "when": {"text_contains": ["pohjola"]}})
    r = run_replay(app, setup, rule)
    assert r.matched == 1 and r.scores == []


def test_a_document_that_passes_the_picture_but_fails_the_person_has_no_picture_score(
    app, setup, fake_archive
):
    from dam.config import Person
    from dam.rules.people import PeopleContext

    people = [Person(name="Anna", match=["anna"]), Person(name="Ben", match=["ben"])]
    rule = setup.rule(person="Anna")
    setup.keep("a", "sha-a", synth.letter())
    ben = PeopleContext(people, (0.0, 0.0, 1.0, 1.0), "Ben")
    c = check(rule, record(), "", people=ben, pictures=setup.pictures)
    assert not c.matched and c.picture_score is None
    # in the replay, the picture score of a non-match is only the picture's own failure
    add(app, fake_archive, "10. Bank/b.pdf", "b", "x")
    setup.keep("b", "sha-b", synth.letter())
    r = run_replay(app, setup, rule, people=people, assigned_persons=lambda: {"b": "Ben"})
    assert r.matched == 0 and r.scores == []
    add(app, fake_archive, "10. Bank/c.pdf", "c", "x")
    setup.keep("c", "sha-c", synth.letter(kind=1))  # another picture: this one is a score
    assigned = {"b": "Ben", "c": "Anna"}
    r = run_replay(app, setup, rule, people=people, assigned_persons=lambda: assigned)
    assert [(s.path, s.matched) for s in r.scores] == [("10. Bank/c.pdf", False)]


def test_an_earlier_text_rule_does_not_make_the_replay_match_pictures_outside_its_budget(
    app, setup, fake_archive, monkeypatch
):
    fill(app, setup, fake_archive, n_match=4, n_other=4)
    earlier = Rule.model_validate(
        {
            "id": "earlier",
            "when": {"zones": [{"box": [0.5, 0.05, 0.95, 0.12], "text_contains": ["x"]}]},
            "then": {"folder": "Elsewhere"},
        }
    )
    rule = setup.rule()
    calls = []
    real = setup.pictures.match

    def counting(*args, **kw):
        calls.append(args)
        return real(*args, **kw)

    monkeypatch.setattr(setup.pictures, "match", counting)
    wide = replay(
        app.engine, rule, [earlier, rule], app.settings.special_folders,
        budget_s=0.0, layouts_for=app.repo.layouts_for, pictures=setup.pictures,
    )  # fmt: skip
    assert wide.truncated and calls == []
    # with time, the matching happens once per document (ten rows), in the main loop
    full = replay(
        app.engine, rule, [earlier, rule], app.settings.special_folders,
        layouts_for=app.repo.layouts_for, pictures=setup.pictures,
    )  # fmt: skip
    assert full.matched == 4 and len(calls) == 10


# --- not mistaking one dark logo or one block of small text for another -----------------


@pytest.mark.parametrize("a", ["kela", "KELA", "circle", "folk", "wide"])
@pytest.mark.parametrize("b", ["kela", "KELA", "circle", "folk", "wide"])
def test_two_different_dark_logos_on_white_do_not_come_near_the_threshold(a, b, tmp_path):
    if a == b:
        return
    box = synth.TEXT_LOGO_BOX
    crop = cut_crop(page_picture(synth.dark_logo(a)), box)
    # measured 0.38 to 0.63; "Kela" against "KELA" (the same word) is the closest pair
    assert score_of(synth.dark_logo(b), tmp_path, crop=crop, box=box) < 0.70


def test_a_block_of_other_words_in_the_same_layout_is_below_the_threshold(tmp_path):
    box = synth.TEXT_BLOCK_BOX
    crop = cut_crop(page_picture(synth.text_block(synth.BLOCK_A)), box)
    other = score_of(synth.text_block(synth.BLOCK_B), tmp_path, crop=crop, box=box)
    same = score_of(synth.text_block(synth.BLOCK_A), tmp_path, crop=crop, box=box)
    assert other < DEFAULT_MIN_SCORE - 0.08  # measured 0.74 (0.89 at half the resolution)
    assert same > 0.98


@pytest.mark.parametrize(
    "label,change",
    [
        ("noisy", lambda im: synth.noisy(im, 25)),
        ("darker", lambda im: synth.brightened(im, 0.6)),
        ("skewed 1 degree", lambda im: synth.skewed(im, 1)),
        ("skewed 2 degrees", lambda im: synth.skewed(im, 2)),
    ],
)
def test_a_dark_logo_and_a_block_of_small_text_are_found_in_a_rescan(label, change, tmp_path):
    for page, box, floor in (
        (synth.dark_logo("kela"), synth.TEXT_LOGO_BOX, DEFAULT_MIN_SCORE + 0.05),
        # fine print is the hardest: a 2 degree skew moves its ends by 14 px (measured 0.82)
        (
            synth.text_block(synth.BLOCK_A),
            synth.TEXT_BLOCK_BOX,
            0.78 if label == "skewed 2 degrees" else DEFAULT_MIN_SCORE,
        ),
    ):
        crop = cut_crop(page_picture(page), box)
        assert score_of(change(page), tmp_path, crop=crop, box=box) >= floor, label


# --- who is listed with a picture score --------------------------------------------------


def _zone_rule(setup, text_word="hakemus", min_score=None, **when):
    picture = {"box": list(BOX), "image": "areas/acme-1.png"}
    if min_score is not None:
        picture["min_score"] = min_score
    return Rule.model_validate(
        {
            "id": "acme",
            "when": {
                "zones": [{"box": [0.5, 0.05, 0.95, 0.12], "text_contains": [text_word]}, picture],
                **when,
            },
            "then": {"folder": "Acme"},
        }
    )


def test_a_document_that_fails_a_text_area_is_never_listed_with_a_picture_score(
    app, setup, fake_archive
):
    """The word is in the document's text, only not in the area: whatever the picture
    shows, it is not a near miss of the picture."""
    rule = _zone_rule(setup)
    in_area = layout(("Hakemus", (0.55, 0.06, 0.9, 0.09)))
    elsewhere = layout(("Hakemus", (0.10, 0.60, 0.40, 0.63)))
    for drive_id, rel, page, img in (
        ("w", "10. Bank/wrong-place.pdf", elsewhere, synth.letter()),  # picture matches
        ("n", "10. Bank/near.pdf", in_area, synth.letter(kind=1)),  # the picture is what fails
        ("g", "10. Bank/good.pdf", in_area, synth.letter()),
    ):
        add(app, fake_archive, rel, drive_id, "hakemus")
        setup.keep(drive_id, f"sha-{drive_id}", img)
        app.repo.save_layout(drive_id, f"sha-{drive_id}", page)
    wrong = FileRecord(
        drive_id="w", path="10. Bank/wrong-place.pdf", name="x.pdf", ext="pdf", sha256="sha-w"
    )
    c = check(rule, wrong, "hakemus", None, elsewhere, None, setup.pictures)
    assert not c.matched and not c.waiting
    assert c.picture_score is None and c.picture_needed is None
    # the picture alone would have matched it: it is the text area that fails
    in_area_here = check(rule, wrong, "hakemus", None, in_area, None, setup.pictures)
    assert in_area_here.matched
    r = run_replay(app, setup, rule)
    listed = {s.path: s for s in r.scores}
    assert "10. Bank/wrong-place.pdf" not in listed
    assert r.matched == 1 and listed["10. Bank/good.pdf"].matched
    assert r.checked == 3


def test_only_near_misses_are_listed_with_a_score_and_each_has_a_drive_id(app, setup, fake_archive):
    for i in range(2):
        add(app, fake_archive, f"Insurance/Acme/m{i}.pdf", f"m{i}", "x")
        setup.keep(f"m{i}", f"sha-m{i}", synth.letter(shift=(i, 0)))
    add(app, fake_archive, "10. Bank/other.pdf", "o", "x")
    setup.keep("o", "sha-o", synth.letter(kind=1))
    other = score_of(synth.letter(kind=1), setup.rules_dir.parent)
    assert 0.2 < other < 0.84
    # far below what is needed: not listed; within 0.15 of it: listed, with its id
    far = Rule.model_validate(
        {
            "id": "acme",
            "when": {
                "zones": [
                    {
                        "box": list(BOX),
                        "image": "areas/acme-1.png",
                        "min_score": round(other + 0.2, 2),
                    }
                ]
            },
        }
    )
    close = Rule.model_validate(
        {
            "id": "acme",
            "when": {
                "zones": [
                    {
                        "box": list(BOX),
                        "image": "areas/acme-1.png",
                        "min_score": round(other + 0.1, 2),
                    }
                ]
            },
        }
    )
    r = run_replay(app, setup, far)
    assert [s for s in r.scores if not s.matched] == []
    r = run_replay(app, setup, close)
    (near,) = [s for s in r.scores if not s.matched]
    assert near.path == "10. Bank/other.pdf" and near.drive_id == "o"
    assert near.needed == pytest.approx(round(other + 0.1, 2)) and near.needed - near.score <= 0.15
    assert all(s.drive_id for s in r.scores)


# --- testing the rest ---------------------------------------------------------------------


def test_a_replay_that_stopped_at_its_budget_goes_on_from_where_it_stopped(
    app, setup, fake_archive, monkeypatch
):
    import types

    from dam.rules import replay as replay_module

    fill(app, setup, fake_archive, n_match=4, n_other=3)
    rule = setup.rule()
    whole = run_replay(app, setup, rule)

    ticks = iter(range(10_000))
    monkeypatch.setattr(
        replay_module, "time", types.SimpleNamespace(monotonic=lambda: float(next(ticks)))
    )
    parts, after = [], None
    while True:
        part = run_replay(app, setup, rule, budget_s=4.5, after=after)
        parts.append(part)
        if not part.truncated:
            break
        assert part.next_after is not None and part.next_after != after
        after = part.next_after
    assert len(parts) > 1
    assert all(p.total == whole.total for p in parts)
    assert sum(p.matched for p in parts) == whole.matched
    assert sum(p.same for p in parts) == whole.same
    assert sum(p.checked for p in parts) == whole.checked
    assert sorted(h.drive_id for p in parts for h in p.different) == sorted(
        h.drive_id for h in whole.different
    )
    assert sorted(n.path for p in parts for n in p.not_checked) == sorted(
        n.path for n in whole.not_checked
    )
    # nothing is looked at twice: each part starts after the one before
    assert parts[-1].next_after is None


def test_after_skips_what_comes_before_it(app, setup, fake_archive):
    fill(app, setup, fake_archive)
    whole = run_replay(app, setup, setup.rule())
    rest = run_replay(app, setup, setup.rule(), after="10. Bank/s0.pdf")
    assert rest.total == whole.total and rest.matched == 3
    assert rest.checked == whole.checked - 1  # s0 comes before the cursor
    assert [s.path for s in rest.scores if not s.matched] == [
        "10. Bank/s1.pdf"
    ]  # s0 is before the cursor
