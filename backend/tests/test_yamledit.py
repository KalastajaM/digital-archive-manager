"""Editing single values in a YAML file the owner wrote, keeping everything else."""

import pytest
import yaml

from dam.core.yamledit import YamlEditError, replace_values


def _rename(old: str, new: str):
    def change(path, value):
        if path and path[-1] in ("folder", "folder_is") and value.startswith(f"{old}/"):
            return new + value[len(old) :]
        return None

    return change


RULES = """\
# my rules
- id: car  # the car papers
  when: {text_contains: ["auto"], folder_is: Old years/inbox}
  then:
    folder: Old years/2009   # where they go
    name: "{doc_date:%Y}_car"
- id: bank
  then: {folder: "10. Financial/Banks"}
"""


def test_plain_value_replaced_comments_kept():
    text, lines = replace_values(RULES, _rename("Old years", "Archive disk"))
    assert "    folder: Archive disk/2009   # where they go\n" in text
    assert text.startswith("# my rules\n- id: car  # the car papers\n")
    assert lines == [3, 5]
    data = yaml.safe_load(text)
    assert data[0]["then"]["folder"] == "Archive disk/2009"
    assert data[1] == yaml.safe_load(RULES)[1]


def test_flow_mapping_value_edited_in_place():
    text, _ = replace_values(RULES, _rename("Old years", "Disk"))
    assert '  when: {text_contains: ["auto"], folder_is: Disk/inbox}\n' in text


def test_quoted_value_keeps_quotes():
    source = "- then:\n    folder: 'Old years/it''s'\n- then:\n    folder: \"Old years/x\"\n"
    text, _ = replace_values(source, _rename("Old years", "Vanhat"))
    assert "folder: 'Vanhat/it''s'" in text and 'folder: "Vanhat/x"' in text
    assert yaml.safe_load(text)[0]["then"]["folder"] == "Vanhat/it's"


def test_plain_value_that_needs_quotes_gets_them():
    text, _ = replace_values("folder: Old years/a\n", _rename("Old years", "#1: new"))
    assert yaml.safe_load(text) == {"folder": "#1: new/a"}


def test_nothing_to_change_returns_text_as_is():
    assert replace_values(RULES, _rename("Nope", "X")) == (RULES, [])


def test_folded_scalar_refused_with_line():
    source = "- then:\n    folder: >\n      Old years/2009\n"
    with pytest.raises(YamlEditError) as e:
        replace_values(source, _rename("Old years", "X"))
    assert str(e.value).startswith("line 2:")


def test_multi_line_plain_scalar_refused():
    source = "folder: Old years/a\n  b\n"
    with pytest.raises(YamlEditError):
        replace_values(source, _rename("Old years", "X"))


def test_alias_refused():
    source = "a: &f\n  folder: Old years/a\nb: *f\n"
    with pytest.raises(YamlEditError) as e:
        replace_values(source, _rename("Old years", "X"))
    assert "alias" in str(e.value)


def test_paths_name_keys_and_indices():
    seen = []
    replace_values("a:\n  - x\n  - {b: y}\n", lambda p, v: seen.append((p, v)))
    assert seen == [(("a", 0), "x"), (("a", 1, "b"), "y")]


def test_plain_value_in_flow_mapping_quoted_when_it_must_be():
    text, _ = replace_values("then: {folder: Old years/a, name: x}\n", _rename("Old years", "A, B"))
    assert yaml.safe_load(text) == {"then": {"folder": "A, B/a", "name": "x"}}
    assert '"A, B/a"' in text
