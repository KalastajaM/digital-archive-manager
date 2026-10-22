"""Tray defaults: show what a newer default tray file adds, and add only that."""

import json
from datetime import datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from dam.api import create_api
from dam.trays import defaults

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}

USER_TO_PAY = """\
# my bills tray (edited by hand)
id: to-pay
name: Bills                    # renamed
order: 1
item_title: "{name}"
fields:
  payee:     { type: text, prefill: payee, copy: true }
  due_date:  { type: date, required: true, prefill: due_date }
  amount:    { type: money, prefill: total }
  reference: { type: reference, prefill: reference, copy: true }
  note:      { type: text }      # my own field
date_field: due_date
done: { label: "Paid!" }
reminders:
  - { days_before: 1 }
"""


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


@pytest.fixture
def user_file(app):
    path = app.trays_dir / "10-to-pay.yaml"
    path.write_text(USER_TO_PAY, encoding="utf-8")
    app.reload_rules()
    return path


ALL = ["fields.amount.copy", "fields.iban", "done.fields", "summary"]


def apply(client, tray, diff, paths=None):
    return client.post(
        f"/api/trays/{tray}/apply-defaults",
        json={
            "paths": diff["paths"] if paths is None else paths,
            "expect_current_text": diff["current_text"],
            "expect_new_text": diff["new_text"],
        },
        headers=LOCAL_ORIGIN,
    )


def test_diff_lists_only_missing_keys(app, client, user_file):
    r = client.get("/api/trays/to-pay/defaults-diff")
    assert r.status_code == 200
    diff = r.json()
    assert diff["file"] == "10-to-pay.yaml"
    assert diff["current_text"] == USER_TO_PAY
    assert diff["added"] == [
        # a key the user's field lacks is added too (its other values stay)
        {"path": "fields.amount.copy", "value": True, "problem": None},
        {
            "path": "fields.iban",
            "value": {"type": "iban", "prefill": "iban", "copy": True},
            "problem": None,
        },
        {
            "path": "done.fields",
            "value": {"paid_on": {"type": "date", "default": "today"}},
            "problem": None,
        },
        {"path": "summary", "value": {"sum": "amount"}, "problem": None},
    ]
    assert diff["paths"] == ALL and diff["error"] is None


def test_apply_defaults_only_adds(app, client, user_file):
    diff = client.get("/api/trays/to-pay/defaults-diff").json()
    original = user_file.read_bytes()
    r = apply(client, "to-pay", diff)
    assert r.status_code == 200, r.text
    assert r.json()["file"] == "10-to-pay.yaml"
    backup = app.trays_dir / r.json()["backup"]
    assert backup.name.startswith("10-to-pay.yaml.bak-")
    assert backup.read_bytes() == original  # byte for byte

    text = user_file.read_text(encoding="utf-8")
    assert text == diff["new_text"]
    # the user's comments and formatting stay
    for i, line in enumerate(USER_TO_PAY.splitlines()[:12]):
        if i != 8:  # the amount line: its flow mapping gains ``copy``
            assert line + "\n" in text
    data = yaml.safe_load(text)
    # every user value kept
    assert data["name"] == "Bills"
    assert data["fields"]["amount"] == {"type": "money", "prefill": "total", "copy": True}
    assert "  amount:    {type: money, prefill: total, copy: true}\n" in text
    assert data["fields"]["note"] == {"type": "text"}
    assert data["done"]["label"] == "Paid!"
    assert data["reminders"] == [{"days_before": 1}]
    # the missing keys added
    assert data["fields"]["iban"] == {"type": "iban", "prefill": "iban", "copy": True}
    assert data["done"]["fields"] == {"paid_on": {"type": "date", "default": "today"}}
    assert data["summary"] == {"sum": "amount"}
    assert list(data["fields"]) == ["payee", "due_date", "amount", "reference", "note", "iban"]
    # reloaded
    tray = next(t for t in app.tray_defs if t.id == "to-pay")
    assert "iban" in tray.fields and tray.name == "Bills"
    assert app.tray_errors == []
    # now nothing is missing
    again = client.get("/api/trays/to-pay/defaults-diff").json()
    assert again["added"] == [] and again["new_text"] == again["current_text"] == text


def test_apply_a_subset(app, client, user_file):
    diff = client.get(
        "/api/trays/to-pay/defaults-diff", params={"paths": ["fields.iban", "summary"]}
    ).json()
    assert diff["paths"] == ["fields.iban", "summary"]
    assert [a["path"] for a in diff["added"]] == ALL  # everything is still offered
    r = apply(client, "to-pay", diff)
    assert r.status_code == 200, r.text
    data = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert "iban" in data["fields"] and data["summary"] == {"sum": "amount"}
    assert "copy" not in data["fields"]["amount"]  # not chosen: not added
    assert data["done"] == {"label": "Paid!"}
    left = client.get("/api/trays/to-pay/defaults-diff").json()
    assert [a["path"] for a in left["added"]] == ["fields.amount.copy", "done.fields"]


def test_subset_must_match_the_preview(app, client, user_file):
    diff = client.get("/api/trays/to-pay/defaults-diff", params={"paths": ["summary"]}).json()
    # the same text claimed for another subset is stale
    r = apply(client, "to-pay", diff, paths=["fields.iban"])
    assert r.status_code == 400 and r.json()["code"] == "stale_preview"
    # a path that is not missing (any more) is stale
    r = apply(client, "to-pay", diff, paths=["summary", "name"])
    assert r.status_code == 400 and r.json()["code"] == "stale_preview"
    assert user_file.read_text(encoding="utf-8") == USER_TO_PAY


def test_dismissed_path_no_longer_offered(app, client, user_file):
    r = client.post(
        "/api/trays/to-pay/defaults-dismiss",
        json={"paths": ["fields.amount.copy", "not.offered"]},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200
    assert r.json() == {"dismissed": ["fields.amount.copy"]}
    diff = client.get("/api/trays/to-pay/defaults-diff").json()
    assert [a["path"] for a in diff["added"]] == ["fields.iban", "done.fields", "summary"]
    assert diff["paths"] == ["fields.iban", "done.fields", "summary"]
    # stored in the data dir, never in the tray file
    store = app.app_paths.data_dir / "tray-defaults-dismissed.json"
    assert json.loads(store.read_text(encoding="utf-8")) == {"to-pay": ["fields.amount.copy"]}
    assert user_file.read_text(encoding="utf-8") == USER_TO_PAY
    # applying everything offered leaves the dismissed key out
    assert apply(client, "to-pay", diff).status_code == 200
    data = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert "copy" not in data["fields"]["amount"]
    assert client.get("/api/trays/to-pay/defaults-diff").json()["added"] == []
    # dismissing a path that is not offered is refused quietly
    r = client.post(
        "/api/trays/to-pay/defaults-dismiss", json={"paths": ["summary"]}, headers=LOCAL_ORIGIN
    )
    assert r.json() == {"dismissed": ["fields.amount.copy"]}


def test_incompatible_key_does_not_block_a_compatible_one(app, client):
    # the user made amount a text field: the default summary (a money sum) cannot apply
    (app.trays_dir / "10-to-pay.yaml").write_text(
        "id: to-pay\nname: To pay\norder: 1\nfields:\n  amount: { type: text }\n", encoding="utf-8"
    )
    diff = client.get("/api/trays/to-pay/defaults-diff").json()
    problems = {a["path"]: a["problem"] for a in diff["added"]}
    assert "money field" in problems["summary"]
    assert problems["fields.iban"] is None
    assert "summary" not in diff["paths"] and "fields.iban" in diff["paths"]
    assert diff["error"] is None
    assert apply(client, "to-pay", diff).status_code == 200
    data = yaml.safe_load((app.trays_dir / "10-to-pay.yaml").read_text(encoding="utf-8"))
    assert "iban" in data["fields"] and "summary" not in data
    # choosing the incompatible key explicitly is previewed with an error and refused
    bad = client.get("/api/trays/to-pay/defaults-diff", params={"paths": ["summary"]}).json()
    assert "money field" in bad["error"]
    r = apply(client, "to-pay", bad)
    assert r.status_code == 409


def test_apply_defaults_refuses_stale(app, client, user_file):
    diff = client.get("/api/trays/to-pay/defaults-diff").json()
    user_file.write_text(USER_TO_PAY.replace("Bills", "Bills 2"), encoding="utf-8")
    r = apply(client, "to-pay", diff)
    assert r.status_code == 400
    assert r.json()["code"] == "stale_preview"
    assert user_file.read_text(encoding="utf-8") == USER_TO_PAY.replace("Bills", "Bills 2")
    assert list(app.trays_dir.glob("*.bak-*")) == []


def test_apply_refuses_a_stale_current_text(app, client, user_file):
    diff = client.get("/api/trays/to-pay/defaults-diff").json()
    r = apply(client, "to-pay", {**diff, "current_text": "id: to-pay\n"})
    assert r.status_code == 400 and r.json()["code"] == "stale_preview"
    assert user_file.read_text(encoding="utf-8") == USER_TO_PAY


def test_untouched_and_custom_trays_have_empty_diff(app, client):
    diff = client.get("/api/trays/to-read/defaults-diff").json()
    assert diff["file"] == "30-to-read.yaml"
    assert diff["added"] == [] and diff["new_text"] == diff["current_text"]
    (app.trays_dir / "40-mine.yaml").write_text(
        "id: mine\nname: Mine\norder: 4\n", encoding="utf-8"
    )
    app.reload_rules()
    diff = client.get("/api/trays/mine/defaults-diff").json()
    assert diff == {
        "file": "40-mine.yaml",
        "added": [],
        "paths": [],
        "current_text": "id: mine\nname: Mine\norder: 4\n",
        "new_text": "id: mine\nname: Mine\norder: 4\n",
        "error": None,
        "dismissed": [],
    }
    assert apply(client, "mine", diff).status_code == 422  # nothing chosen
    assert apply(client, "mine", diff, paths=["summary"]).status_code == 400
    assert client.get("/api/trays/nope/defaults-diff").status_code == 404


def test_block_style_nested_insert_and_no_trailing_newline(tmp_path):
    user, dflt = tmp_path / "user", tmp_path / "defaults"
    user.mkdir()
    dflt.mkdir()
    (dflt / "t.yaml").write_text(
        "id: t\nname: T\norder: 2\nfields:\n  a: { type: text }\n  b: { type: date }\n"
        "done:\n  label: Done\n  fields:\n    when: { type: date, default: today }\n",
        encoding="utf-8",
    )
    (user / "t.yaml").write_text(
        "id: t\nname: Mine\norder: 2\nfields:\n  a:\n    type: text   # block style\n"
        "done:\n  label: Finished\n\n# a trailing comment",
        encoding="utf-8",
    )
    diff = defaults.defaults_diff(user, dflt, "t")
    assert [a.path for a in diff.added] == ["fields.b", "done.fields"]
    data = yaml.safe_load(diff.new_text)
    assert data["name"] == "Mine" and data["done"]["label"] == "Finished"
    assert data["fields"] == {"a": {"type": "text"}, "b": {"type": "date"}}
    assert data["done"]["fields"] == {"when": {"type": "date", "default": "today"}}
    assert "    type: text   # block style\n  b: {type: date}\n" in diff.new_text
    assert diff.new_text.endswith("# a trailing comment")
    file, backup = defaults.apply_defaults(
        user, dflt, "t", diff.paths, diff.current_text, diff.new_text, now=datetime(2026, 10, 21)
    )
    assert (file, backup.name) == ("t.yaml", "t.yaml.bak-20261021-000000")
    text = (user / "t.yaml").read_text(encoding="utf-8")
    with pytest.raises(Exception, match="no longer missing"):
        defaults.apply_defaults(user, dflt, "t", ["fields.b"], text, text)


def test_invalid_result_is_refused(tmp_path):
    user, dflt = tmp_path / "user", tmp_path / "defaults"
    user.mkdir()
    dflt.mkdir()
    # the default's summary names a money field the user removed
    (dflt / "t.yaml").write_text(
        "id: t\nname: T\norder: 2\nfields:\n  amount: { type: money }\nsummary: { sum: amount }\n",
        encoding="utf-8",
    )
    (user / "t.yaml").write_text(
        "id: t\nname: T\norder: 2\nfields:\n  amount: { type: text }\n", encoding="utf-8"
    )
    diff = defaults.defaults_diff(user, dflt, "t")
    assert [a.path for a in diff.added] == ["summary"]
    assert "must name a money field" in diff.added[0].problem
    assert diff.paths == [] and diff.new_text == diff.current_text


def dismiss(client, paths, undo=False):
    route = "defaults-undismiss" if undo else "defaults-dismiss"
    return client.post(f"/api/trays/to-pay/{route}", json={"paths": paths}, headers=LOCAL_ORIGIN)


def test_dismissed_list_and_undismiss(app, client, user_file):
    # nothing dismissed yet: the list is empty (and absent without ?dismissed=1)
    diff = client.get("/api/trays/to-pay/defaults-diff", params={"dismissed": 1}).json()
    assert diff["dismissed"] == []
    assert dismiss(client, ["fields.iban", "summary"]).json() == {
        "dismissed": ["fields.iban", "summary"]
    }
    diff = client.get("/api/trays/to-pay/defaults-diff", params={"dismissed": 1}).json()
    assert diff["dismissed"] == ["fields.iban", "summary"]
    assert [a["path"] for a in diff["added"]] == ["fields.amount.copy", "done.fields"]
    # without the flag the list is not computed
    assert client.get("/api/trays/to-pay/defaults-diff").json()["dismissed"] == []
    # undismiss one: offered again, the other stays dismissed
    r = dismiss(client, ["summary", "not.dismissed"], undo=True)
    assert r.status_code == 200
    assert r.json() == {"dismissed": ["fields.iban"]}
    diff = client.get("/api/trays/to-pay/defaults-diff", params={"dismissed": 1}).json()
    assert [a["path"] for a in diff["added"]] == ["fields.amount.copy", "done.fields", "summary"]
    assert diff["dismissed"] == ["fields.iban"]
    store = app.app_paths.data_dir / "tray-defaults-dismissed.json"
    assert json.loads(store.read_text(encoding="utf-8")) == {"to-pay": ["fields.iban"]}
    assert user_file.read_text(encoding="utf-8") == USER_TO_PAY  # never the tray file


def test_dismissed_list_leaves_out_keys_no_longer_missing(app, client, user_file):
    dismiss(client, ["summary"])
    # the user adds the key by hand: it is no longer listed as dismissed
    user_file.write_text(USER_TO_PAY + "summary: { sum: amount }\n", encoding="utf-8")
    diff = client.get("/api/trays/to-pay/defaults-diff", params={"dismissed": 1}).json()
    assert diff["dismissed"] == []


def test_undismiss_needs_paths(client, user_file):
    assert dismiss(client, [], undo=True).status_code == 422


def test_undismiss_unknown_tray_is_404(client, user_file):
    r = client.post(
        "/api/trays/nope/defaults-undismiss", json={"paths": ["summary"]}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 404


# -- final wave: the lock, a failed tray write, a store that does not read back -------


def _pair(tmp_path):
    user, dflt = tmp_path / "user", tmp_path / "defaults"
    user.mkdir()
    dflt.mkdir()
    (dflt / "t.yaml").write_text(
        "id: t\nname: T\norder: 2\nfields:\n  a: { type: text }\n"
        "  b: { type: text }\n  c: { type: text }\n",
        encoding="utf-8",
    )
    (user / "t.yaml").write_text(
        "id: t\nname: T\norder: 2\nfields:\n  a: { type: text }\n", encoding="utf-8"
    )
    return user, dflt


NOW = datetime(2026, 10, 21, 1, 2, 3)


def _apply(user, dflt, paths=("fields.b",)):
    diff = defaults.defaults_diff(user, dflt, "t", list(paths))
    return defaults.apply_defaults(
        user, dflt, "t", list(paths), diff.current_text, diff.new_text, now=NOW
    )


def test_failed_tray_write_puts_the_original_back_and_names_the_backup(tmp_path, monkeypatch):
    user, dflt = _pair(tmp_path)
    tray = user / "t.yaml"
    original = tray.read_bytes()
    real = defaults._write_bytes

    def disk_full(path, data):
        if path == tray and data != original:
            with open(path, "wb") as fh:
                fh.write(data[:7])  # half written
            raise OSError(28, "No space left on device")
        real(path, data)

    monkeypatch.setattr(defaults, "_write_bytes", disk_full)
    with pytest.raises(defaults.Conflict) as caught:
        _apply(user, dflt)
    message = str(caught.value)
    assert "t.yaml.bak-20261021-010203" in message
    assert "No space left on device" in message
    assert tray.read_bytes() == original  # put back
    assert (user / "t.yaml.bak-20261021-010203").read_bytes() == original


def test_tray_write_and_restore_both_failing_says_to_restore_from_the_backup(tmp_path, monkeypatch):
    user, dflt = _pair(tmp_path)
    tray = user / "t.yaml"

    def broken(path, data):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(defaults, "_write_bytes", broken)
    with pytest.raises(defaults.Conflict) as caught:
        _apply(user, dflt)
    message = str(caught.value)
    assert "restore it from" in message and "t.yaml.bak-20261021-010203" in message
    assert tray.exists()


def test_dismiss_store_that_does_not_read_back_keeps_its_previous_content(tmp_path, monkeypatch):
    user, dflt = _pair(tmp_path)
    store = tmp_path / "data" / "dismissed.json"
    assert defaults.dismiss(store, user, dflt, "t", ["fields.b"]) == ["fields.b"]
    before = store.read_bytes()
    real = defaults._write_bytes

    def truncating(path, data):
        if path == store and data != before:
            real(path, data[: len(data) // 2])  # written short, no error raised
            return
        real(path, data)

    monkeypatch.setattr(defaults, "_write_bytes", truncating)
    with pytest.raises(defaults.Conflict, match="Could not save"):
        defaults.dismiss(store, user, dflt, "t", ["fields.c"])
    assert store.read_bytes() == before
    with pytest.raises(defaults.Conflict, match="Could not save"):
        defaults.undismiss(store, "t", ["fields.b"])
    assert store.read_bytes() == before
    monkeypatch.setattr(defaults, "_write_bytes", real)
    assert defaults.load_dismissed(store) == {"t": ["fields.b"]}


def test_dismissals_at_the_same_time_both_stay(tmp_path, monkeypatch):
    import threading
    import time

    user, dflt = _pair(tmp_path)
    store = tmp_path / "dismissed.json"
    real = defaults.load_dismissed

    def slow(path):
        data = real(path)
        time.sleep(0.15)  # a second dismissal reads the same store meanwhile
        return data

    monkeypatch.setattr(defaults, "load_dismissed", slow)
    threads = [
        threading.Thread(target=defaults.dismiss, args=(store, user, dflt, "t", [p]))
        for p in ("fields.b", "fields.c")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(real(store)["t"]) == ["fields.b", "fields.c"]
