import pytest
from sqlalchemy import func, select

from dam.db.tables import checklist_items, notes
from dam.notes import CHECK_MAX, NOTE_MAX, ChecklistItem, NotesService
from dam.services.errors import InvalidRequest, NotFound


@pytest.fixture
def svc(engine):
    return NotesService(engine)


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_get_missing_is_empty(svc):
    assert svc.get("file", "d1") == ""


def test_set_get_replace_and_strip(engine, svc):
    svc.set("file", "d1", "  hello \n")
    assert svc.get("file", "d1") == "hello"
    svc.set("file", "d1", "bye")
    assert svc.get("file", "d1") == "bye"
    assert count(engine, notes) == 1


def test_kinds_are_separate(svc):
    svc.set("file", "1", "a")
    svc.set("item", "1", "b")
    svc.set("collection", "1", "c")
    assert [svc.get(k, "1") for k in ("file", "item", "collection")] == ["a", "b", "c"]


def test_blank_text_removes_row(engine, svc):
    svc.set("item", "3", "x")
    svc.set("item", "3", "  \n ")
    assert svc.get("item", "3") == ""
    assert count(engine, notes) == 0
    svc.set("item", "3", "")  # nothing to remove: fine


def test_invalid_kind_and_caps(svc):
    with pytest.raises(InvalidRequest):
        svc.get("tray", "1")
    with pytest.raises(InvalidRequest):
        svc.set("bogus", "1", "x")
    with pytest.raises(InvalidRequest):
        svc.checklist("bogus", "1")
    with pytest.raises(InvalidRequest):
        svc.add_check("bogus", "1", "x")
    svc.set("file", "d", "x" * NOTE_MAX)
    with pytest.raises(InvalidRequest):
        svc.set("file", "d", "x" * (NOTE_MAX + 1))
    svc.add_check("file", "d", "y" * CHECK_MAX)
    with pytest.raises(InvalidRequest):
        svc.add_check("file", "d", "y" * (CHECK_MAX + 1))
    with pytest.raises(InvalidRequest):
        svc.add_check("file", "d", "   ")


def test_append_adds_below_the_note_and_never_overwrites(engine, svc):
    assert svc.append("file", "d1", "first") == "first"  # no note yet
    assert svc.append("file", "d1", "  second \n") == "first\n\nsecond"
    assert svc.get("file", "d1") == "first\n\nsecond"
    assert svc.append("file", "d1", "   ") == "first\n\nsecond"  # blank: unchanged
    assert svc.append("file", "other", "x") == "x"
    assert count(engine, notes) == 2


def test_append_over_the_limit_is_refused_and_keeps_the_note(svc):
    svc.set("file", "d1", "a" * (NOTE_MAX - 5))
    with pytest.raises(InvalidRequest):
        svc.append("file", "d1", "b" * 10)
    assert svc.get("file", "d1") == "a" * (NOTE_MAX - 5)
    with pytest.raises(InvalidRequest):
        svc.append("sideways", "d1", "x")


def test_append_clears_a_batch_owner_like_a_user_edit(engine, svc):
    svc.set("file", "d1", "from filing", batch_id="b1")
    svc.append("file", "d1", "mine")
    assert svc.remove_created_by("b1") == 0
    assert svc.get("file", "d1") == "from filing\n\nmine"


def test_remove_created_by_only_matching_notes(engine, svc):
    svc.set("file", "a", "one", batch_id="b1")
    svc.set("file", "b", "two", batch_id="b2")
    svc.set("file", "c", "three")
    svc.add_check("file", "a", "keep")
    assert svc.remove_created_by("b1") == 1
    assert svc.get("file", "a") == ""
    assert svc.get("file", "b") == "two"
    assert svc.get("file", "c") == "three"
    assert count(engine, checklist_items) == 1
    assert svc.remove_created_by("nope") == 0


def test_checklist_add_and_order(svc):
    a = svc.add_check("item", "1", " first ")
    b = svc.add_check("item", "1", "second")
    svc.add_check("item", "2", "other")
    assert isinstance(a, ChecklistItem)
    assert (a.text, a.done, a.position, b.position) == ("first", False, 0, 1)
    assert [c.text for c in svc.checklist("item", "1")] == ["first", "second"]
    assert svc.checklist("item", "9") == []


def test_set_check_done_and_text(svc):
    a = svc.add_check("item", "1", "x")
    svc.set_check(a.id, done=True)
    c = svc.checklist("item", "1")[0]
    assert (c.done, c.text) == (True, "x")
    svc.set_check(a.id, text=" y ")
    svc.set_check(a.id, done=False)
    c = svc.checklist("item", "1")[0]
    assert (c.done, c.text) == (False, "y")
    with pytest.raises(InvalidRequest):
        svc.set_check(a.id, text="")
    with pytest.raises(InvalidRequest):
        svc.set_check(a.id, text="z" * (CHECK_MAX + 1))
    with pytest.raises(NotFound):
        svc.set_check(999, done=True)


def test_remove_check_renumbers(svc):
    ids = [svc.add_check("item", "1", t).id for t in "abc"]
    svc.add_check("item", "2", "z")
    svc.remove_check(ids[0])
    got = svc.checklist("item", "1")
    assert [(c.text, c.position) for c in got] == [("b", 0), ("c", 1)]
    assert [c.position for c in svc.checklist("item", "2")] == [0]
    with pytest.raises(NotFound):
        svc.remove_check(ids[0])


def test_move_check_order_and_clamp(svc):
    a, b, c, d = (svc.add_check("item", "1", t) for t in "abcd")
    other = svc.add_check("item", "2", "o")

    def order():
        return [(x.text, x.position) for x in svc.checklist("item", "1")]

    svc.move_check(d.id, 0)
    assert order() == [("d", 0), ("a", 1), ("b", 2), ("c", 3)]
    svc.move_check(d.id, 2)
    assert order() == [("a", 0), ("b", 1), ("d", 2), ("c", 3)]
    svc.move_check(a.id, 99)
    assert order() == [("b", 0), ("d", 1), ("c", 2), ("a", 3)]
    svc.move_check(a.id, -5)
    assert order() == [("a", 0), ("b", 1), ("d", 2), ("c", 3)]
    assert [(x.text, x.position) for x in svc.checklist("item", "2")] == [("o", 0)]
    assert other.position == 0
    with pytest.raises(NotFound):
        svc.move_check(999, 0)


def test_user_edit_takes_note_over_from_batch(svc):
    svc.set("file", "a", "filed", batch_id="b1")
    svc.set("file", "a", "edited")
    assert svc.remove_created_by("b1") == 0
    assert svc.get("file", "a") == "edited"


def test_set_check_without_changes(svc):
    a = svc.add_check("item", "1", "x")
    svc.set_check(a.id)
    c = svc.checklist("item", "1")[0]
    assert (c.text, c.done, c.position) == ("x", False, 0)
    svc.set_check(a.id, done=True)
    assert svc.checklist("item", "1")[0].done is True


def test_concurrent_add_check_positions_are_dense(svc):
    import threading

    def work():
        for _ in range(50):
            svc.add_check("item", "1", "x")

    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [c.position for c in svc.checklist("item", "1")] == list(range(100))


def test_batch_does_not_take_over_a_user_note(svc):
    svc.set("file", "a", "mine")
    svc.set("file", "a", "filed", batch_id="b2")
    assert svc.remove_created_by("b2") == 0
    assert svc.get("file", "a") == "filed"


def test_readers_do_not_wait_for_a_writer(engine):
    import threading

    from dam.db.engine import write_tx
    from dam.index.repo import FileRepo

    svc = NotesService(engine)
    svc.set("file", "a", "x")
    held, release, result = threading.Event(), threading.Event(), {}

    def writer():
        with write_tx(engine):
            held.set()
            release.wait(10)

    t = threading.Thread(target=writer)
    t.start()
    held.wait(10)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA busy_timeout=100")
            assert conn.exec_driver_sql("SELECT count(*) FROM notes").scalar() == 1
        assert FileRepo(engine, "00. Inbox").get("nope") is None
        assert svc.get("file", "a") == "x"
        result["ok"] = True
    finally:
        release.set()
        t.join()
    assert result["ok"]


def test_write_transactions_serialise(engine):
    import threading

    from dam.db.engine import write_tx

    inside, order = 0, []
    lock = threading.Lock()

    def work():
        nonlocal inside
        with write_tx(engine):
            with lock:
                inside += 1
                order.append(inside)
            import time

            time.sleep(0.05)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert order == [1, 1, 1]


def test_read_nested_in_write_tx_on_same_thread_returns(engine):
    from dam.db.engine import write_tx

    svc = NotesService(engine)
    svc.set("file", "a", "x")
    with write_tx(engine) as w:
        w.exec_driver_sql("PRAGMA busy_timeout=100")
        with engine.connect() as r:
            r.exec_driver_sql("PRAGMA busy_timeout=100")
            assert r.exec_driver_sql("SELECT count(*) FROM notes").scalar() == 1
