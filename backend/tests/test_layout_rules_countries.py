import yaml

from dam import layouts
from dam.config import DEFAULTS_DIR


def test_the_finland_examples_come_only_with_finland():
    assert "Finland examples" in layouts.rules_text([], countries=["fi"])
    assert "Finland examples" not in layouts.rules_text([], countries=[])
    # unset: as before there was a choice
    assert "Finland examples" in layouts.rules_text([])


def test_the_netherlands_examples_come_only_with_the_netherlands():
    text = layouts.rules_text([], countries=["nl"])
    assert "Netherlands examples" in text and "# - id: belastingdienst" in text
    assert "Finland examples" not in text
    assert "Netherlands examples" not in layouts.rules_text([])
    both = layouts.rules_text([], countries=["fi", "nl"])
    assert "Finland examples" in both and "Netherlands examples" in both
    # commented out, so the file holds only the layout's rules
    assert yaml.safe_load(text) == []


def test_the_netherlands_examples_are_valid_rules():
    from dam.rules.model import Rule

    path = DEFAULTS_DIR / "countries" / "nl" / "rules.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [Rule.model_validate(r).id for r in raw] == [
        "belastingdienst",
        "gemeente-belastingen",
        "energienota",
    ]
