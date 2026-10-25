"""The search query language: words and filters taken apart (``dam.query``)."""

import pytest

from dam.query import Filter, QueryError, date_span, extensions_of, format_filter, parse_query


def parse(text):
    p = parse_query(text)
    return p.words, [(f.name, f.value, f.negated) for f in p.filters]


def test_plain_words_only():
    assert parse("northpower  invoice ") == ("northpower invoice", [])
    assert parse("") == ("", [])


@pytest.mark.parametrize(
    "name,value",
    [
        ("name", "x"),
        ("in", "x"),
        ("tag", "x"),
        ("collection", "x"),
        ("from", "x"),
        ("for", "x"),
        ("type", "x"),
        ("before", "2026"),
        ("after", "2026-10-01"),
        ("tray", "x"),
        ("is", "note"),
    ],
)
def test_each_filter_name_is_known(name, value):
    assert parse(f"{name}:{value}") == ("", [(name, value, False)])


def test_date_is_and_values():
    assert parse("date:2026-10") == ("", [("date", "2026-10", False)])
    assert parse("is:Locked") == ("", [("is", "locked", False)])  # is: values are lower case


def test_filters_and_words_mix_in_any_order():
    assert parse("tag:insurance kela letter type:pdf") == (
        "kela letter",
        [("tag", "insurance", False), ("type", "pdf", False)],
    )


def test_quotes_keep_spaces_in_a_value():
    assert parse('in:"50. Medical" tag:"two words"') == (
        "",
        [("in", "50. Medical", False), ("tag", "two words", False)],
    )
    # an unterminated quote takes the rest
    assert parse('collection:"House sale') == ("", [("collection", "House sale", False)])


def test_dash_excludes_any_filter():
    assert parse('-tag:paid -in:"90. Other People"') == (
        "",
        [("tag", "paid", True), ("in", "90. Other People", True)],
    )


def test_names_are_not_case_sensitive():
    assert parse("TAG:Kela") == ("", [("tag", "Kela", False)])


def test_unknown_names_are_plain_words():
    assert parse("http://example.org foo:bar") == ("http://example.org foo:bar", [])
    assert parse("-5 e-mail") == ("-5 e-mail", [])
    assert parse("tags:x") == ("tags:x", [])  # not a filter name


def test_a_colon_inside_a_word_is_not_a_filter():
    assert parse("xtag:a") == ("xtag:a", [])


def test_quoted_phrase_is_words():
    assert parse('"annual report" 2026') == ("annual report 2026", [])


def test_wildcards_stay_in_the_value():
    assert parse("name:*kela* name:2026?") == (
        "",
        [("name", "*kela*", False), ("name", "2026?", False)],
    )


def test_type_is_lower_case_and_loses_the_dot():
    assert parse("type:.PDF") == ("", [("type", "pdf", False)])


@pytest.mark.parametrize(
    "text",
    [
        "tag:",
        'in:""',
        "is:",
        "is:nope",
        "date:2026-13",
        "date:2026-02-30",
        "date:soon",
        "after:26",
        "before:2026-1",
        "type:pdf!",
        "type:waytoolongextension",
    ],
)
def test_bad_values_are_refused(text):
    with pytest.raises(QueryError):
        parse_query(text)


def test_error_text_says_what_is_wrong():
    with pytest.raises(QueryError, match="Use YYYY, YYYY-MM or YYYY-MM-DD"):
        parse_query("date:x")
    with pytest.raises(QueryError, match="starred, important, locked, todo, note, summary"):
        parse_query("is:x")


def test_date_span():
    from datetime import date

    assert date_span("2026") == (date(2026, 1, 1), date(2027, 1, 1))
    assert date_span("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    assert date_span("2026-02") == (date(2026, 2, 1), date(2026, 3, 1))
    assert date_span("2024-02-29") == (date(2024, 2, 29), date(2024, 3, 1))


def test_type_groups_and_extensions():
    assert extensions_of("pdf") == ("pdf",)
    assert "png" in extensions_of("image") and "heic" in extensions_of("image")
    assert "docx" in extensions_of("doc") and "xlsx" in extensions_of("sheet")
    assert extensions_of("zzz") == ("zzz",)


def test_format_filter_round_trips():
    for text in ("tag:kela", '-in:"50. Medical"', "type:pdf", 'collection:"House sale"'):
        (f,) = parse_query(text).filters
        assert format_filter(f) == text
    assert format_filter(Filter("tag", 'a"b c')) == 'tag:"ab c"'
