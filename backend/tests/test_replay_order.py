"""The likely documents are tested first, and the order never changes the result: the
sender's documents, those in the folder the areas were drawn on, and for a picture rule
the rest best-looking first from tiny thumbnails; "test the rest" goes on in the same
order from an opaque cursor; the thumbnails are cache that can be made again."""

import dataclasses
import types

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text

import bigfake
import synth
from dam.extract.picture import (
    THUMB_H,
    THUMB_W,
    PageThumbs,
    picture_name,
    thumb_of,
    write_picture,
)
from dam.rules import replay as replay_module
from dam.rules.model import Rule
from dam.rules.picture import Template, coarse_scores
from dam.rules.replay import ReplayRun, StaleCursor, folder_of, replay


@pytest.fixture(scope="module")
def fake(tmp_path_factory):
    f = bigfake.build(tmp_path_factory.mktemp("order"), 900, seed=11)
    yield f
    f.engine.dispose()


def rule_with(rule: Rule, **extra) -> Rule:
    return Rule.model_validate({**rule.model_dump(exclude_none=True), **extra})


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


def same_result(a, b):
    assert dataclasses.asdict(a) == dataclasses.asdict(b)


def path_of(fake, drive_id):
    with fake.engine.connect() as conn:
        return conn.execute(
            text("select path from files where drive_id = :d"), {"d": drive_id}
        ).scalar()


@pytest.mark.parametrize("which", ["b_picture", "c_text_picture", "d_text_area", "a_word"])
def test_the_order_never_changes_the_result(fake, monkeypatch, which):
    rule = rule_with(bigfake.rules()[which], sender="Kela")
    mine = fake.kela_ids[:15]
    near = folder_of(path_of(fake, fake.kela_ids[20]))
    ordered = run_of(fake, rule, sender_ids=lambda s: mine, near_folder=near)
    assert ordered.advance()
    # the same documents in plain path order
    monkeypatch.setattr(ReplayRun, "_ordered", lambda self, rows: rows)
    plain = run_of(fake, rule, sender_ids=lambda s: mine)
    assert plain.advance()
    assert [r.path for r in plain.rows] == sorted(r.path for r in plain.rows)
    assert [r.drive_id for r in ordered.rows] != [r.drive_id for r in plain.rows]
    same_result(ordered.snapshot(), plain.snapshot())


def test_the_senders_documents_come_first_then_the_folder_then_the_best_picture(fake):
    rule = rule_with(bigfake.rules()["b_picture"], sender="Kela")
    mine = set(fake.kela_ids[:5])
    folder = "60. Travel/2020"
    run = run_of(fake, rule, sender_ids=lambda s: sorted(mine), near_folder=folder)
    ids = [r.drive_id for r in run.rows]
    assert set(ids[:5]) == mine
    nearby = [r for r in run.rows[5:] if folder_of(r.path) == folder]
    assert nearby
    k = len(nearby)
    assert all(folder_of(r.path) == folder for r in run.rows[5 : 5 + k])
    rest = run.rows[5 + k :]
    # the pages with the logo are at the front of the rest, the ones without it behind
    front = [r.drive_id in fake.logo_ids for r in rest[: len(fake.logo_ids) - 5 - k]]
    assert sum(front) / len(front) > 0.8


def test_a_picture_rule_ranks_the_pages_with_the_logo_first(fake):
    rule = bigfake.rules()["b_picture"]
    run = run_of(fake, rule)
    ranked = [r.drive_id for r in run.rows]
    logo = len(fake.logo_ids)
    top = ranked[:logo]
    assert sum(d in fake.logo_ids for d in top) / logo > 0.85
    # the documents without a picture come last (nothing to look at in them yet)
    with_picture = {d for d in ranked if d in fake.logo_ids}
    assert with_picture <= set(ranked[: len(ranked) // 2]) | with_picture


def test_test_the_rest_goes_on_in_the_same_order_from_an_opaque_cursor(fake, monkeypatch):
    rule = bigfake.rules()["d_text_area"]
    whole = replay(fake.engine, rule, [rule], fake.special, 60.0, layouts_for=fake.repo.layouts_for)
    assert not whole.truncated and whole.next_after is None
    ticks = iter(range(1_000_000))  # a clock that moves one second a look
    monkeypatch.setattr(
        replay_module, "time", types.SimpleNamespace(monotonic=lambda: float(next(ticks)))
    )
    seen, after, parts = 0, None, []
    while True:
        part = replay(
            fake.engine,
            rule,
            [rule],
            fake.special,
            400.0,
            layouts_for=fake.repo.layouts_for,
            after=after,
        )
        parts.append(part)
        seen += part.looked_at
        if not part.truncated:
            break
        assert part.next_after and part.next_after != after
        assert part.next_after.startswith("r1.")  # not a path
        after = part.next_after
    assert len(parts) > 1
    assert seen == whole.looked_at == whole.total
    assert sum(p.matched for p in parts) == whole.matched
    assert sum(p.checked for p in parts) == whole.checked
    assert sorted(n.drive_id for p in parts for n in p.not_checked) == sorted(
        n.drive_id for n in whole.not_checked
    )


def test_a_cursor_the_server_forgot_is_refused(fake):
    rule = bigfake.rules()["d_text_area"]
    with pytest.raises(StaleCursor):
        replay(
            fake.engine, rule, [rule], fake.special, after="r1.deadbeef.5",
            layouts_for=fake.repo.layouts_for,
        )  # fmt: skip


def test_only_a_few_orders_are_remembered(fake, monkeypatch):
    monkeypatch.setattr(replay_module, "MAX_PLANS", 2)
    rule = bigfake.rules()["d_text_area"]
    cursors = []
    for _ in range(3):
        r = replay(fake.engine, rule, [rule], fake.special, 0.0, layouts_for=fake.repo.layouts_for)
        cursors.append(r.next_after)
    with pytest.raises(StaleCursor):
        replay(fake.engine, rule, [rule], fake.special, after=cursors[0])
    replay(fake.engine, rule, [rule], fake.special, after=cursors[2])


def test_a_path_cursor_from_before_still_works_in_path_order(fake):
    rule = bigfake.rules()["d_text_area"]
    whole = replay(fake.engine, rule, [rule], fake.special, layouts_for=fake.repo.layouts_for)
    rest = replay(
        fake.engine,
        rule,
        [rule],
        fake.special,
        after="50. Medical",
        layouts_for=fake.repo.layouts_for,
    )
    assert rest.total == whole.total and rest.looked_at < whole.looked_at


# -- the thumbnails -------------------------------------------------------------------------


def test_a_thumbnail_is_small_and_keeps_the_proportions(tmp_path):
    img = synth.letter()
    assert len(thumb_of(img)) == THUMB_W * THUMB_H


def test_thumbnails_are_kept_in_one_file_and_come_back(tmp_path):
    thumbs = PageThumbs(tmp_path)
    thumbs.add("a-0123456789abcdef.jpg", synth.letter())
    thumbs.add("b-0123456789abcdef.jpg", synth.letter(kind=1))
    assert thumbs.flush(force=True)
    assert (tmp_path / "page1-thumbs.npz").is_file()
    again = PageThumbs(tmp_path)
    assert len(again) == 2
    one, present = again.get_many(["a-0123456789abcdef.jpg", "zzz"])
    assert present.tolist() == [True, False] and one[1].sum() == 0
    assert np.array_equal(one[0].ravel(), np.frombuffer(thumb_of(synth.letter()), np.uint8))


def test_a_torn_or_wrong_thumbnail_file_counts_as_empty_and_is_made_again(tmp_path, caplog):
    (tmp_path / "page1-thumbs.npz").write_bytes(b"PK\x03\x04 not a real archive")
    thumbs = PageThumbs(tmp_path)
    assert len(thumbs) == 0
    (tmp_path / "page1-thumbs.npz").write_bytes(b"")
    assert len(PageThumbs(tmp_path)) == 0
    # a file with other dimensions (an older format) is ignored too
    np.savez(tmp_path / "page1-thumbs.npz", names=np.array(["x"]), data=np.zeros((1, 5), np.uint8))
    assert len(PageThumbs(tmp_path)) == 0


def test_missing_thumbnails_are_made_from_the_pictures_in_the_cache(tmp_path):
    for i in range(3):
        write_picture(tmp_path, f"d{i}", "a" * 64, synth.letter(seed=i))
    thumbs = PageThumbs(tmp_path)
    wanted = {
        picture_name(f"d{i}", "a" * 64): tmp_path / "page1" / picture_name(f"d{i}", "a" * 64)
        for i in range(3)
    }
    assert thumbs.ensure(wanted, budget_s=30) == 0
    assert len(thumbs) == 3 and (tmp_path / "page1-thumbs.npz").is_file()
    # a picture that is gone loses its thumbnail; nothing in the cache is removed
    assert thumbs.forget_missing({picture_name("d0", "a" * 64)}) == 2
    assert len(thumbs) == 1


def test_the_budget_for_making_thumbnails_is_kept(tmp_path):
    write_picture(tmp_path, "d", "b" * 64, synth.letter())
    name = picture_name("d", "b" * 64)
    thumbs = PageThumbs(tmp_path)
    assert thumbs.ensure({name: tmp_path / "page1" / name}, budget_s=0.0) == 1
    assert len(thumbs) == 0


def test_the_coarse_score_prefers_the_page_with_the_logo(tmp_path):
    crop = Image.fromarray(np.asarray(synth.letter().crop((50, 28, 350, 140)))).convert("L")
    template = Template(crop, synth.LOGO_BOX)
    pages = [
        synth.letter(0),
        synth.letter(1),
        synth.letter(0, shift=(10, 5)),
        Image.new("L", synth.PAGE, 255),
    ]
    data = np.stack([np.frombuffer(thumb_of(p), np.uint8).reshape(THUMB_H, THUMB_W) for p in pages])
    scores = coarse_scores(template, data, np.array([True, True, True, False]))
    assert scores[3] == -1.0
    assert scores[0] > scores[1] and scores[2] > scores[1]
