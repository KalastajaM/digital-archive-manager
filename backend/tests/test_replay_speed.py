"""The speed of the rule test: folding is exact and done once per document, a rule without
words never reads the text, a file with no page 1 is settled without a look, the picture
score does not change when only the search window is blurred, the time of each step is
logged, and the result on a fake archive built to the size of a real one (a small one
here) equals a document-by-document check."""

import logging
import random
import unicodedata

import pytest
from PIL import Image

import bigfake
from dam.index.repo import FileRecord
from dam.rules import replay as replay_module
from dam.rules.engine import check
from dam.rules.model import Rule, fold
from dam.rules.picture import Template, load_gray, load_page, match, match_gray
from dam.rules.replay import ReplayRun, replay


def reference_fold(s: str) -> str:
    d = unicodedata.normalize("NFKD", s)
    return "".join(c for c in d if not unicodedata.combining(c)).casefold()


def test_fold_equals_dropping_every_combining_character():
    rnd = random.Random(5)
    pools = [
        (32, 126),
        (0xA0, 0x24F),
        (0x300, 0x36F),
        (0x370, 0x1FFF),
        (0x2000, 0x2FFF),
        (0xFB00, 0xFFEF),
    ]
    for _ in range(1500):
        s = "".join(chr(rnd.randint(*rnd.choice(pools))) for _ in range(rnd.randint(0, 80)))
        assert fold(s) == reference_fold(s), s
    for s in ["", "ASCII only", "Kansaneläkelaitos ÄÖÅ é", "ß ﬁ Ａｂ ǩ İ", "ạ̈b", "x\U0001d165y"]:
        assert fold(s) == reference_fold(s), s


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    fake = bigfake.build(tmp_path_factory.mktemp("bigfake"), 700, seed=3)
    yield fake
    fake.engine.dispose()


def run_of(fake, rule, **kw):
    return ReplayRun(
        fake.engine,
        rule,
        [rule],
        fake.special,
        layouts_for=fake.repo.layouts_for,
        pictures=fake.pictures,
        **kw,
    )


def brute_force(fake, rule):
    """The counts of ``rule`` by looking at one document at a time, in no clever way."""
    from sqlalchemy import select

    from dam.db.tables import file_text, files
    from dam.rules.replay import without_folder

    free = without_folder(rule)
    out = {"matched": 0, "checked": 0, "not_checked": 0}
    with fake.engine.connect() as conn:
        rows = conn.execute(
            select(files, file_text.c.text).join(
                file_text, file_text.c.drive_id == files.c.drive_id
            )
        ).all()
    for r in rows:
        rec = FileRecord(drive_id=r.drive_id, path=r.path, name=r.name, ext=r.ext, sha256=r.sha256)
        c = check(
            free,
            rec,
            fold(r.text or ""),
            None,
            fake.repo.layout_for(r.drive_id),
            None,
            fake.pictures,
        )
        if c.waiting:
            out["not_checked"] += 1
        else:
            out["checked"] += 1
            out["matched"] += int(c.matched)
    return out


@pytest.mark.parametrize("which", ["a_word", "b_picture", "c_text_picture", "d_text_area"])
def test_the_fake_archive_gives_the_counts_of_a_check_of_each_document(small, which):
    rule = bigfake.rules()[which]
    run = run_of(small, rule)
    assert run.advance()
    r = run.snapshot()
    want = brute_force(small, rule)
    assert (r.matched, r.checked, len(r.not_checked)) == (
        want["matched"],
        want["checked"],
        want["not_checked"],
    )
    assert r.total == small.n_files and r.looked_at == r.total
    assert r.matched > 0 or which == "d_text_area"


def test_a_text_area_folds_each_text_once(small, monkeypatch):
    calls = []
    real = replay_module.fold
    monkeypatch.setattr(replay_module, "fold", lambda s: calls.append(len(s)) or real(s))
    run = run_of(small, bigfake.rules()["c_text_picture"])
    run.advance()
    media = sum(1 for r in run.rows if (r.ext or "") in ("pdf", "jpg", "png"))
    assert len(calls) == media  # one fold per document that can have a page 1, not two
    assert run.timings.text_chars == sum(calls)


def test_a_picture_only_rule_never_reads_or_folds_the_text(small, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the text was used")

    monkeypatch.setattr(replay_module, "fold", boom)
    monkeypatch.setattr(ReplayRun, "_fetch_texts", boom)
    run = run_of(small, bigfake.rules()["b_picture"])
    assert run.advance()
    assert run.snapshot().matched > 0


def test_a_rule_with_areas_settles_files_with_no_page_1_without_a_look(small):
    run = run_of(small, bigfake.rules()["d_text_area"])
    run.advance()
    assert run.timings.layouts_loaded <= small.layouts
    no_page1 = sum(1 for r in run.rows if (r.ext or "") not in ("pdf", "jpg", "jpeg", "png"))
    assert no_page1 > 0
    assert run.checked + len(run.not_checked) == run.total


def test_the_search_window_alone_is_blurred_with_the_same_score(small):
    crop = Image.open(small.rules_dir / "areas" / "bench-1.png")
    crop.load()
    template = Template(crop, bigfake.BOX)
    pictures = sorted((small.cache_dir / "page1").glob("*.jpg"))[:12]
    assert pictures
    for path in pictures:
        old, new = match(template, load_page(path)), match_gray(template, load_gray(path))
        assert (old.score, old.box) == (new.score, new.box)


def test_each_replay_logs_where_its_time_went_in_numbers_only(small, caplog):
    rule = bigfake.rules()["d_text_area"]
    with caplog.at_level(logging.INFO, logger="dam.rules.replay"):
        replay(
            small.engine,
            rule,
            [rule],
            small.special,
            layouts_for=small.repo.layouts_for,
            pictures=small.pictures,
        )
    lines = [m for m in caplog.messages if m.startswith("rule test:")]
    assert len(lines) == 1
    for step in ("sql=", "fold=", "layouts=", "zones=", "picture_load=", "ncc=", "other="):
        assert step in lines[0]
    assert "kela" not in lines[0].lower() and "/" not in lines[0]


def test_a_rule_that_can_match_a_page_with_words_only_is_unchanged(small):
    """Words in the file's text only (no areas): the files with no page 1 count too."""
    rule = Rule.model_validate(
        {"id": "w", "when": {"text_contains": ["lasku"]}, "then": {"folder": "11. Bills"}}
    )
    r = replay(small.engine, rule, [rule], small.special)
    want = brute_force(small, rule)
    assert (r.matched, r.checked) == (want["matched"], want["checked"])
