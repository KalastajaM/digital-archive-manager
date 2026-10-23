"""The filing codes API: list, replace, warnings and problems."""

from test_api import LOCAL_ORIGIN, make_client


def put(client, url, body):
    return client.put(url, json=body, headers=LOCAL_ORIGIN)


def test_get_lists_seeded_codes(app):
    with make_client(app) as c:
        r = c.get("/api/filing-codes")
    assert r.status_code == 200
    data = r.json()
    assert [x["code"] for x in data["codes"]] == ["A", "P", "F"]
    assert data["problems"] == []
    assert data["warnings"] == []


def test_put_replaces_and_warns(app):
    with make_client(app) as c:
        r = put(c, "/api/filing-codes", [{"code": "0"}, {"code": "O"}])
        assert r.status_code == 200, r.text
        data = r.json()
        assert [x["code"] for x in data["codes"]] == ["0", "O"]
        warn = {w["code"]: w["confusable_with"] for w in data["warnings"]}
        assert warn == {"0": ["O"], "O": ["0"]}
        again = c.get("/api/filing-codes").json()
    assert [x["code"] for x in again["codes"]] == ["0", "O"]
    assert [c.code for c in app.codes] == ["0", "O"]


def test_put_unknown_tray_400(app):
    with make_client(app) as c:
        r = put(c, "/api/filing-codes", [{"code": "X", "tray": "no-such-tray"}])
        assert r.status_code == 400
        assert "no-such-tray" in r.json()["error"]
        assert [x["code"] for x in c.get("/api/filing-codes").json()["codes"]] == ["A", "P", "F"]


def test_put_invalid_code_400(app):
    with make_client(app) as c:
        r = put(c, "/api/filing-codes", [{"code": "A"}, {"code": "TOOLONG"}])
        assert r.status_code == 400
        err = r.json()["error"]
        assert "TOOLONG" in err and "1 to 4" in err and "Value error" not in err
        assert [x["code"] for x in c.get("/api/filing-codes").json()["codes"]] == ["A", "P", "F"]


def test_put_padded_duplicate_inbox_folder_400(app):
    body = [
        {"code": "X", "inbox_folder": "To pay"},
        {"code": "Y", "inbox_folder": " To pay"},
    ]
    with make_client(app) as c:
        r = put(c, "/api/filing-codes", body)
        assert r.status_code == 400
        assert "used twice" in r.json()["error"]
        assert [x["code"] for x in c.get("/api/filing-codes").json()["codes"]] == ["A", "P", "F"]


def test_get_reports_hand_edit_problem(app):
    path = app.app_paths.filing_codes_path
    path.write_text(path.read_text(encoding="utf-8") + "- code: TOOLONG\n", encoding="utf-8")
    app.reload_rules()
    with make_client(app) as c:
        data = c.get("/api/filing-codes").json()
    assert len(data["problems"]) == 1
    assert data["problems"][0]["code"] == "TOOLONG"
    assert len(data["codes"]) == 3
