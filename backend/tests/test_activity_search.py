"""GET /api/activity: server-side search, filters and cursor paging over the journal."""

import pytest

from dam.db.engine import write_tx
from dam.db.tables import operations
from test_api import make_client

DAY = 86400.0
T0 = 1_760_000_000.0  # a fixed "now"


@pytest.fixture
def client(app):
    with make_client(app) as c:
        yield c


def _batch(app, batch_id, created, ops, *, label=None, origin="ui", undo_of=None, state="done"):
    """Journal rows of one batch, written directly: ``ops`` are (kind, src, dst)."""
    with write_tx(app.engine) as conn:
        for seq, (kind, src, dst) in enumerate(ops):
            conn.execute(
                operations.insert().values(
                    batch_id=batch_id,
                    seq=seq,
                    kind=kind,
                    src=src,
                    dst=dst,
                    state=state,
                    origin=origin,
                    undo_of=undo_of,
                    created=created,
                    label=label,
                )
            )


def _seed(app):
    _batch(
        app,
        "filed",
        T0,
        [("move", "##. Organize/scan.pdf", "10. Financial/Banks/Lasku Äiti.pdf")],
        label="Filed Lasku Äiti.pdf into 10. Financial/Banks",
    )
    _batch(
        app,
        "moved",
        T0 + 1,
        [("move", "10. Financial/a.pdf", "13. Taxes/a.pdf")],
        label="Moved a.pdf to 13. Taxes",
    )
    _batch(
        app,
        "renamed",
        T0 + 2,
        [("rename", "13. Taxes/a.pdf", "13. Taxes/b.pdf")],
        label="Renamed a.pdf to b.pdf",
    )
    _batch(
        app,
        "coll",
        T0 + 3,
        [("symlink", "x.pdf", "##. Ongoing/Trip/x.pdf")],
        label="Added x.pdf to Trip",
    )
    _batch(app, "star", T0 + 4, [("symlink", "x.pdf", "##. Ongoing/x.pdf")], label="Starred x.pdf")
    _batch(
        app,
        "important",
        T0 + 5,
        [("symlink", "y.pdf", "##. Important/y.pdf")],
        label="Marked y.pdf as important",
    )
    _batch(
        app,
        "trash",
        T0 + 6,
        [("quarantine", "13. Taxes/b.pdf", "##. To Delete/13. Taxes/b.pdf")],
        label="Moved b.pdf to To Delete",
    )
    _batch(
        app,
        "convert",
        T0 + 7,
        [("move", "Trip/z.pdf", "##. Ongoing/Trip/z.pdf")],
        label="Converted Trip into Trip",
    )
    _batch(
        app, "sync", T0 + 8, [("symlink", "x.pdf", "##. Ongoing/Trip/x2.pdf")], origin="workflow"
    )
    _batch(app, "cli", T0 + 9, [("move", "q/old.pdf", "r/old.pdf")], origin="cli")  # no label
    _batch(
        app,
        "undo",
        T0 + 10,
        [("move", "13. Taxes/b.pdf", "10. Financial/b.pdf")],
        origin="undo",
        undo_of="trash",
    )
    _batch(
        app,
        "failed",
        T0 + 11,
        [("move", "m/f.pdf", "n/f.pdf")],
        state="failed",
        label="Moved f.pdf to n",
    )


def ids(client, **params):
    r = client.get("/api/activity", params=params)
    assert r.status_code == 200, r.text
    return [b["batch_id"] for b in r.json()]


def test_no_filters_lists_newest_first(client, app):
    _seed(app)
    got = ids(client)
    assert got[0] == "failed" and got[-1] == "filed" and len(got) == 12


def test_text_search_matches_titles_and_paths_ignoring_case_and_accents(client, app):
    _seed(app)
    assert ids(client, q="lasku aiti") == ["filed"]  # accent and case folded
    assert ids(client, q="LASKU ÄITI") == ["filed"]
    # a file name finds every change that touched it, whatever the title says
    assert set(ids(client, q="a.pdf")) == {"moved", "renamed"}
    assert set(ids(client, q="x2.pdf")) == {"sync"}  # in a path only, untitled batch
    assert set(ids(client, q="taxes b.pdf")) == {"renamed", "trash", "undo"}  # all words
    assert ids(client, q="nothing like this") == []
    assert ids(client, q="100%") == []  # LIKE wildcards are literal
    assert ids(client, q="_") == []


def test_kind_filter(client, app):
    _seed(app)
    assert ids(client, kind="undo") == ["undo"]
    assert ids(client, kind="trash") == ["trash"]
    assert set(ids(client, kind="marks")) == {"star", "important"}
    assert ids(client, kind="convert") == ["convert"]
    assert set(ids(client, kind="collections")) == {"coll", "sync"}
    assert ids(client, kind="rename") == ["renamed"]
    assert set(ids(client, kind="filed")) == {"filed", "moved", "cli", "failed"}
    assert set(ids(client, kind=["rename", "trash"])) == {"renamed", "trash"}
    assert client.get("/api/activity", params={"kind": "bogus"}).status_code == 400


def test_origin_filter(client, app):
    _seed(app)
    assert ids(client, origin="cli") == ["cli"]
    assert ids(client, origin="auto") == ["sync"]
    assert "sync" not in ids(client, origin="ui") and "cli" not in ids(client, origin="ui")
    assert client.get("/api/activity", params={"origin": "x"}).status_code == 400


def test_status_filter(client, app):
    _seed(app)
    with write_tx(app.engine) as conn:
        conn.execute(
            operations.update().where(operations.c.batch_id == "moved").values(state="undone")
        )
    assert ids(client, status="undone") == ["moved"]
    assert ids(client, status="attention") == ["failed"]
    undoable = set(ids(client, status="undoable"))
    assert "filed" in undoable and not undoable & {"moved", "sync", "undo", "failed"}
    done = set(ids(client, status="done"))
    assert "filed" in done and "sync" in done and not done & {"moved", "failed"}
    assert client.get("/api/activity", params={"status": "x"}).status_code == 400


def test_date_range(client, app):
    _batch(app, "old", T0 - 40 * DAY, [("move", "a", "b")])
    _batch(app, "mid", T0 - 5 * DAY, [("move", "a", "b")])
    _batch(app, "new", T0, [("move", "a", "b")])
    assert ids(client, since=T0 - 10 * DAY) == ["new", "mid"]
    assert ids(client, until=T0 - 10 * DAY) == ["old"]
    assert ids(client, since=T0 - 10 * DAY, until=T0) == ["mid"]  # until is exclusive


def test_filters_combine(client, app):
    _seed(app)
    assert ids(client, q="b.pdf", kind="trash") == ["trash"]
    assert ids(client, q="b.pdf", kind="trash", origin="cli") == []


def test_paging_by_cursor(client, app):
    _seed(app)
    first = ids(client, limit=5)
    assert len(first) == 5
    second = ids(client, limit=5, before=first[-1])
    third = ids(client, limit=5, before=second[-1])
    assert ids(client, limit=5, before=third[-1]) == []
    assert first + second + third == ids(client)
    # the cursor holds under filters
    moves = ids(client, kind="filed")
    assert ids(client, kind="filed", limit=2, before=moves[1]) == moves[2:4]
    assert client.get("/api/activity", params={"before": "nope"}).status_code == 404


def test_shape_is_still_a_list_of_batches(client, app):
    _seed(app)
    first = client.get("/api/activity", params={"limit": 1}).json()
    assert isinstance(first, list) and first[0]["batch_id"] == "failed" and first[0]["ops"]


def test_new_folder_batches_are_their_own_kind(client, app):
    _batch(
        app,
        "mk",
        T0 + 20,
        [("mkdir", None, "10. Financial/New")],
        label="Created the folder New in 10. Financial",
    )
    _batch(app, "mk-unlabelled", T0 + 21, [("mkdir", None, "a"), ("mkdir", None, "a/b")])
    _batch(app, "mk-sync", T0 + 22, [("mkdir", None, "##. Ongoing/Trip")], origin="workflow")
    _batch(
        app,
        "mk-and-move",
        T0 + 23,
        [("mkdir", None, "d"), ("move", "x.pdf", "d/x.pdf")],
        label="Filed x.pdf into d",
    )
    assert set(ids(client, kind="folders")) == {"mk", "mk-unlabelled"}
    assert "mk-sync" in ids(client, kind="collections")  # the automatic sync stays there
    assert "mk-and-move" in ids(client, kind="filed")
    assert "mk" not in ids(client, kind="filed")
