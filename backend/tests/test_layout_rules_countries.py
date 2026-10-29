from dam import layouts


def test_the_finland_examples_come_only_with_finland():
    assert "Finland examples" in layouts.rules_text([], countries=["fi"])
    assert "Finland examples" not in layouts.rules_text([], countries=[])
    # unset: as before there was a choice
    assert "Finland examples" in layouts.rules_text([])
