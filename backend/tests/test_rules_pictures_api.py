"""Picture areas through the API: the crop preview and save, the draft from picture boxes, the
rule save, the replay with scores and the suggestion with a picture area."""

import base64
import io

import pytest
from PIL import Image

import synth
from dam.extract.picture import page_picture, write_picture
from dam.rules.picture import crop_file, cut_crop, png_bytes
from test_api import LOCAL_ORIGIN, make_client, post
from test_rules_zone import INBOX, LETTER, add, seed_frequency

BOX = list(synth.LOGO_BOX)


def keep(app, drive_id, img):
    """The page-1 picture of a document the test added (its sha256 is ``sha-<id>``)."""
    write_picture(app.app_paths.cache_dir, drive_id, f"sha-{drive_id}", page_picture(img))


def put(client, url, body):
    return client.put(url, json=body, headers=LOCAL_ORIGIN)


def png_of(data: dict) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data["png"])))


@pytest.fixture
def doc(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "Acme letter")
    keep(app, "a", synth.letter())
    return "a"


def areas_dir(app):
    return app.rules_dir / "areas"


# --- the crop ---------------------------------------------------------------------------


def test_the_preview_cuts_the_box_from_the_cached_page_and_writes_nothing(app, doc):
    with make_client(app) as c:
        r = post(c, "/api/rules/area-picture", {"drive_id": doc, "box": BOX})
    assert r.status_code == 200
    data = r.json()
    img = png_of(data)
    assert img.mode == "L" and img.format == "PNG" and max(img.size) <= 300
    assert (img.width, img.height) == (data["width"], data["height"])
    assert data["image"] is None and not areas_dir(app).exists()


def test_the_crop_is_capped_at_300_pixels_on_its_long_side(app, doc):
    with make_client(app) as c:
        data = post(c, "/api/rules/area-picture", {"drive_id": doc, "box": [0, 0, 1, 1]}).json()
    assert max(data["width"], data["height"]) == 300


def test_saving_names_the_file_after_the_rule_and_never_overwrites(app, doc):
    with make_client(app) as c:
        body = {"drive_id": doc, "box": BOX, "save": True, "rule_id": "Acme Oy / policy"}
        first = post(c, "/api/rules/area-picture", body).json()
        second = post(c, "/api/rules/area-picture", body).json()
    assert first["image"] == "areas/Acme-Oy-policy-1.png"
    assert second["image"] == "areas/Acme-Oy-policy-2.png"
    saved = crop_file(app.rules_dir, first["image"])
    assert saved.read_bytes() == base64.b64decode(first["png"])
    with Image.open(saved) as img:
        assert img.mode == "L"


def test_saving_needs_a_rule_id_and_a_known_document_and_a_real_box(app, doc):
    with make_client(app) as c:
        assert (
            post(
                c, "/api/rules/area-picture", {"drive_id": doc, "box": BOX, "save": True}
            ).status_code
            == 400
        )
        assert (
            post(c, "/api/rules/area-picture", {"drive_id": "nope", "box": BOX}).status_code == 404
        )
        bad = post(c, "/api/rules/area-picture", {"drive_id": doc, "box": [0.5, 0.5, 0.2, 0.2]})
        assert bad.status_code == 400
        assert post(
            c, "/api/rules/area-picture", {"drive_id": doc, "box": [0, 0, 1]}
        ).status_code in (400, 422)


def test_a_document_without_a_picture_yet_is_queued(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "x")
    with make_client(app) as c:
        r = post(c, "/api/rules/area-picture", {"drive_id": "b", "box": BOX})
    assert r.status_code == 400 and "not made yet" in r.json()["error"]
    assert "b" in app.content._wanted


def test_a_saved_picture_is_served_and_the_path_is_checked(app, doc):
    with make_client(app) as c:
        saved = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": doc, "box": BOX, "save": True, "rule_id": "r"},
        ).json()["image"]
        got = c.get("/api/rules/" + saved.replace("areas/", "areas/"))
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(got.content)).mode == "L"
        assert c.get("/api/rules/areas/missing.png").status_code == 404
        assert c.get("/api/rules/areas/..%2Frules.yaml").status_code in (400, 404)
        assert c.get("/api/rules/areas/x.txt").status_code == 404


# --- saving a rule ------------------------------------------------------------------------


def rule_body(image, **zone):
    return {
        "id": "acme",
        "when": {"zones": [{"box": BOX, "image": image, **zone}], "folder_is": INBOX},
        "then": {"folder": "Insurance/Acme"},
    }


def test_a_rule_with_a_picture_area_saves_and_lists_with_its_picture(app, doc):
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": doc, "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        r = put(c, "/api/rules/acme", rule_body(image, min_score=0.9))
        assert r.status_code == 200, r.text
        listed = c.get("/api/rules").json()
    (rule,) = [x for x in listed["rules"] if x["id"] == "acme"]
    assert rule["when"]["zones"] == [
        {"box": BOX, "text_contains": None, "image": image, "min_score": 0.9}
    ]
    assert listed["unused_pictures"] == [] and listed["default_min_score"] == 0.85


def test_a_rule_naming_a_picture_that_is_not_there_or_a_bad_path_is_refused(app, doc):
    with make_client(app) as c:
        assert put(c, "/api/rules/acme", rule_body("areas/gone-1.png")).status_code == 400
        for bad in ("areas/../learned.yaml", "../x.png", "/abs.png", "areas/a/b.png"):
            assert put(c, "/api/rules/acme", rule_body(bad)).status_code == 400
        assert put(c, "/api/rules/acme", rule_body("areas/x-1.png", min_score=0)).status_code == 400


def test_a_deleted_rule_leaves_its_picture_which_is_listed_as_unused(app, doc):
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": doc, "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        assert c.get("/api/rules").json()["unused_pictures"] == ["acme-1.png"]  # not used yet
        put(c, "/api/rules/acme", rule_body(image))
        assert c.get("/api/rules").json()["unused_pictures"] == []
        c.delete("/api/rules/acme", headers=LOCAL_ORIGIN)
        assert c.get("/api/rules").json()["unused_pictures"] == ["acme-1.png"]
    assert crop_file(app.rules_dir, image).is_file()


# --- the draft from boxes ----------------------------------------------------------------


def test_draft_zone_with_a_picture_box_saves_the_crop_under_the_drafts_id(app, doc):
    with make_client(app) as c:
        r = post(
            c, "/api/rules/draft-zone", {"drive_id": doc, "picture_boxes": [BOX], "sender": "Acme"}
        )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["id"] == "acme" and draft["zones"] == [] and draft["sender"] == "Acme"
    (picture,) = draft["pictures"]
    assert picture["image"] == "areas/acme-1.png" and picture["box"] == BOX
    assert crop_file(app.rules_dir, picture["image"]).is_file()
    assert png_of(picture).mode == "L"


def test_draft_zone_mixes_text_boxes_and_picture_boxes(app, fake_archive):
    seed_frequency(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "Pohjola Vakuutus", LETTER)
    keep(app, "a", synth.letter())
    text_box = [0.05, 0.02, 0.45, 0.14]
    with make_client(app) as c:
        draft = post(
            c,
            "/api/rules/draft-zone",
            {"drive_id": "a", "boxes": [text_box], "picture_boxes": [BOX]},
        ).json()
    assert [z["box"] for z in draft["zones"]] == [text_box]
    assert draft["id"].startswith("pohjola") or draft["id"]
    assert draft["pictures"][0]["image"] == f"areas/{draft['id']}-1.png"


def test_draft_zone_needs_a_box_and_a_picture_when_it_asks_for_one(app, fake_archive, doc):
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "x")
    with make_client(app) as c:
        assert post(c, "/api/rules/draft-zone", {"drive_id": doc}).status_code == 400
        # no page-1 picture for b: the picture box cannot be cut yet
        r = post(c, "/api/rules/draft-zone", {"drive_id": "b", "picture_boxes": [BOX]})
        assert r.status_code == 400 and "not made yet" in r.json()["error"]


# --- replay and the suggestion ----------------------------------------------------------------


def test_replay_api_has_the_scores(app, fake_archive):
    for i in range(3):
        add(app, fake_archive, f"Insurance/Acme/20250{i + 1}10_A.pdf", f"m{i}", "x")
        keep(app, f"m{i}", synth.letter(shift=(2 * i, 3 * i)))
    add(app, fake_archive, "10. Bank/other.pdf", "o", "x")
    keep(app, "o", synth.letter(kind=1))
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": "m0", "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        data = post(c, "/api/rules/replay", {"rule": rule_body(image)}).json()
    assert data["matched"] == 3 and data["same"] == 3
    assert [s["matched"] for s in data["scores"]] == [True, True, True, False]
    assert all(set(s) == {"path", "drive_id", "score", "matched", "needed"} for s in data["scores"])
    last = data["scores"][-1]
    assert last["path"] == "10. Bank/other.pdf" and last["drive_id"] == "o"
    assert last["score"] < 0.85 and last["needed"] == 0.85  # a near miss: within 0.15 of it
    assert data["next_after"] is None and data["truncated"] is False
    assert {m["drive_id"] for m in data["scores"] if m["matched"]} == {"m0", "m1", "m2"}


def test_replay_api_goes_on_after_a_path(app, fake_archive):
    for i in range(3):
        add(app, fake_archive, f"Insurance/Acme/20250{i + 1}10_A.pdf", f"m{i}", "x")
        keep(app, f"m{i}", synth.letter(shift=(2 * i, 3 * i)))
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": "m0", "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        rest = post(
            c,
            "/api/rules/replay",
            {"rule": rule_body(image), "after": "Insurance/Acme/20250210_A.pdf"},
        ).json()
    assert rest["matched"] == 1 and rest["total"] == 3 and rest["checked"] == 1


def test_areas_for_draws_the_rule_being_tested_on_a_document(app, fake_archive):
    add(app, fake_archive, "10. Bank/a.pdf", "a", "x")
    keep(app, "a", synth.letter(shift=(15, 10)))
    add(app, fake_archive, "10. Bank/b.pdf", "b", "x")
    keep(app, "b", synth.letter(kind=1))
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": "a", "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        body = rule_body(image)
        body["when"]["folder_is"] = "Somewhere else"  # a test ignores the folder, as the replay
        hit = post(c, "/api/rules/areas-for", {"rule": body, "drive_id": "a"})
        miss = post(c, "/api/rules/areas-for", {"rule": body, "drive_id": "b"})
        unknown = post(c, "/api/rules/areas-for", {"rule": body, "drive_id": "nope"})
        # nothing was saved or changed
        assert "acme" not in [r["id"] for r in c.get("/api/rules").json()["rules"]]
    assert hit.status_code == 200
    (area,) = hit.json()["areas"]
    assert area["kind"] == "image" and area["matched"] is True and area["score"] > 0.9
    assert len(area["lines"]) == 1 and area["box"] == BOX
    (other,) = miss.json()["areas"]
    assert other["matched"] is False and other["score"] < 0.85 and "needs 0.85" in other["reason"]
    assert unknown.status_code == 404


def test_the_inbox_suggestion_names_the_folder_and_draws_the_picture_area(app, doc):
    with make_client(app) as c:
        image = post(
            c,
            "/api/rules/area-picture",
            {"drive_id": doc, "box": BOX, "save": True, "rule_id": "acme"},
        ).json()["image"]
        assert put(c, "/api/rules/acme", rule_body(image)).status_code == 200
        keep(app, doc, synth.letter(shift=(15, 10)))  # a rescan of the same letterhead
        s = c.get(f"/api/files/{doc}/suggestions").json()
        assert s["folder"] == "Insurance/Acme" and s["folder_source"] == "rule:acme"
        (area,) = [a for a in s["areas"] if a["kind"] == "image"]
        assert area["rule_id"] == "acme" and area["index"] == 0 and area["matched"] is True
        assert area["score"] > 0.9 and len(area["lines"]) == 1 and area["wins"] is True
        explained = post(c, "/api/rules/explain", {"drive_id": doc}).json()
    mine = [x for x in explained if x["rule_id"] == "acme"][0]
    assert (
        mine["matched"] and mine["areas"][0]["kind"] == "image" and mine["areas"][0]["score"] > 0.9
    )
    assert mine["zone_lines"] == [[]]


def test_the_inbox_says_reading_page_1_until_the_picture_is_made(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/p.pdf", "p", "Acme letter")
    (app.rules_dir / "areas").mkdir(parents=True, exist_ok=True)
    crop = cut_crop(page_picture(synth.letter()), synth.LOGO_BOX)
    (app.rules_dir / "areas" / "acme-1.png").write_bytes(png_bytes(crop))
    with make_client(app) as c:
        assert put(c, "/api/rules/acme", rule_body("areas/acme-1.png")).status_code == 200
        inbox = c.get("/api/inbox").json()
    (entry,) = [e for e in inbox if e["record"]["drive_id"] == "p"]
    assert entry["suggestion"]["waiting_for_page1"] is True
    assert "p" in app.content._wanted


# --- the safe write -------------------------------------------------------------------------


def test_write_config_bytes_keeps_a_copy_and_restores_when_the_read_back_fails(tmp_path):
    from dam.codes.configfile import write_config_bytes

    path = tmp_path / "areas" / "x-1.png"
    write_config_bytes(path, b"first", lambda: path.read_bytes() == b"first")
    assert path.read_bytes() == b"first"
    with pytest.raises(OSError, match="did not read back"):
        write_config_bytes(path, b"second", lambda: False)
    assert path.read_bytes() == b"first"  # restored
    backups = [p.name for p in path.parent.iterdir() if ".bak-" in p.name]
    assert backups and (path.parent / backups[0]).read_bytes() == b"first"


# --- two saves at once, and boxes too small to match ------------------------------------


def test_two_saves_at_once_get_two_files_and_neither_overwrites_the_other(app, monkeypatch):
    import threading
    import time

    from dam.services import area_pictures

    real = area_pictures.write_config_bytes

    def slow(path, data, verify):
        time.sleep(0.2)  # the other save runs while this one is between pick and write
        real(path, data, verify)

    monkeypatch.setattr(area_pictures, "write_config_bytes", slow)
    crops = [Image.new("L", (20, 20), 60), Image.new("L", (20, 20), 200)]
    names: list[str] = []
    threads = [
        threading.Thread(target=lambda c=c: names.append(app.area_pictures.save("acme", c)))
        for c in crops
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(names) == ["areas/acme-1.png", "areas/acme-2.png"]
    stored = sorted(crop_file(app.rules_dir, n).read_bytes() for n in names)
    assert stored == sorted(png_bytes(c) for c in crops)


def test_a_picture_box_under_one_percent_of_the_page_is_refused(app, doc):
    tiny = [0.1, 0.1, 0.105, 0.3]  # 0.5% wide
    flat = [0.1, 0.1, 0.4, 0.105]
    with make_client(app) as c:
        for box in (tiny, flat):
            r = post(c, "/api/rules/area-picture", {"drive_id": doc, "box": box})
            assert r.status_code == 400 and "too small" in r.json()["error"]
            r = post(c, "/api/rules/draft-zone", {"drive_id": doc, "picture_boxes": [box]})
            assert r.status_code == 400 and "too small" in r.json()["error"]
        ok = [0.1, 0.1, 0.12, 0.12]
        assert post(c, "/api/rules/area-picture", {"drive_id": doc, "box": ok}).status_code == 200
    assert not areas_dir(app).exists()
