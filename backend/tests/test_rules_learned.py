import pytest

from dam.errors import InvalidRequest, NotFound
from dam.rules.model import LEARNED_FILE, Rule, load_rules


def _write(app, name, text):
    app.rules_dir.mkdir(parents=True, exist_ok=True)
    (app.rules_dir / name).write_text(text, encoding="utf-8")


def _clear(app):
    for p in app.rules_dir.glob("*.yaml"):
        p.unlink()
    app.reload_rules()


def test_learned_file_loads_first(app):
    _clear(app)
    _write(app, "00-examples.yaml", "- id: invoice\n  when: {text_contains: [lasku]}\n")
    _write(app, LEARNED_FILE, "- id: fortum\n  when: {text_contains: [fortum]}\n")
    rules, errors = load_rules(app.rules_dir)
    assert not errors
    assert [r.id for r in rules] == ["fortum", "invoice"]


def test_save_rule_creates_learned_file_and_reloads(app):
    _clear(app)
    app.save_rule(
        Rule(id="fortum", when={"text_contains": ["fortum"]}, then={"folder": "11. Bills/{year}"})
    )
    assert (app.rules_dir / "learned.yaml").is_file()
    assert app.rules[0].id == "fortum"


def test_editing_a_hand_written_rule_keeps_its_conditions_and_neighbours(app):
    _clear(app)
    _write(
        app,
        "10-mine.yaml",
        '- id: a\n  when: {filename_matches: "(?i)^scan", folder_is: "##. Organize"}\n'
        "  then: {folder: Old}\n- id: b\n  when: {text_contains: [x]}\n",
    )
    app.reload_rules()
    edited = next(r for r in app.rules if r.id == "a").model_copy(deep=True)
    edited.then.folder = "New"
    app.save_rule(edited, replaces="a")
    rules, errors = load_rules(app.rules_dir)
    assert not errors
    assert [r.id for r in rules] == ["a", "b"]
    a = rules[0]
    assert a.when.filename_matches == "(?i)^scan"
    assert a.when.folder_is == "##. Organize"
    assert a.then.folder == "New"
    assert not (app.rules_dir / LEARNED_FILE).exists()
    assert list(app.rules_dir.glob("10-mine.yaml.bak-*"))


def test_save_rule_refuses_a_duplicate_id(app):
    _clear(app)
    app.save_rule(Rule(id="x", when={"text_contains": ["x"]}))
    with pytest.raises(InvalidRequest):
        app.save_rule(Rule(id="x", when={"text_contains": ["y"]}))
    app.save_rule(Rule(id="x", when={"text_contains": ["y"]}), replaces="x")
    assert app.rules[0].when.text_contains == ["y"]


def test_delete_and_move_learned_rules(app):
    _clear(app)
    _write(app, "10-mine.yaml", "- id: hand\n  when: {text_contains: [h]}\n")
    for rid in ("one", "two", "three"):
        app.save_rule(Rule(id=rid, when={"text_contains": [rid]}))
    assert [r.id for r in app.rules] == ["one", "two", "three", "hand"]
    app.move_rule("three", -1)
    assert [r.id for r in app.rules][:3] == ["one", "three", "two"]
    app.move_rule("one", 10)
    assert [r.id for r in app.rules][:3] == ["three", "two", "one"]
    with pytest.raises(InvalidRequest, match="only learned rules"):
        app.move_rule("hand", 1)
    app.delete_rule("two")
    assert [r.id for r in app.rules] == ["three", "one", "hand"]
    app.delete_rule("hand")
    assert [r.id for r in app.rules] == ["three", "one"]
    with pytest.raises(NotFound):
        app.delete_rule("nope")
