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
    assert parse("e-mail 5-6") == ("e-mail 5-6", [])
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


def terms(text):
    p = parse_query(text)
    return [[(t.text, t.phrase, t.prefix) for t in c] for c in p.clauses], [
        (t.text, t.phrase, t.prefix) for t in p.excluded
    ]


def test_the_last_word_is_a_prefix_filters_after_it_or_not():
    assert terms("kela lasku") == ([[("kela", False, False)], [("lasku", False, True)]], [])
    assert terms("kela type:pdf")[0] == [[("kela", False, True)]]


def test_a_star_makes_any_word_a_prefix():
    assert terms("vakuut* kela")[0] == [[("vakuut", False, True)], [("kela", False, True)]]


def test_a_closed_phrase_is_exact_an_open_one_still_typing():
    assert terms('"annual report"') == ([[("annual report", True, False)]], [])
    assert terms('"annual rep') == ([[("annual rep", True, True)]], [])


def test_dash_and_not_exclude_words():
    assert terms("kela -lasku NOT draft") == (
        [[("kela", False, True)]],
        [("lasku", False, False), ("draft", False, False)],
    )
    assert terms('-"house sale" x')[1] == [("house sale", True, False)]
    # a dash alone, or inside a word, excludes nothing
    assert terms("e-mail - x")[1] == []


def test_or_joins_the_words_next_to_it():
    assert terms("vakuutus kela OR if") == (
        [[("vakuutus", False, False)], [("kela", False, False), ("if", False, True)]],
        [],
    )
    # a filter between the words does not break it (chips go after the words)
    assert terms("kela tag:x OR kelan")[0] == [[("kela", False, False), ("kelan", False, True)]]
    # nothing to join: an OR at either end, or next to an exclusion, is dropped
    assert terms("OR kela OR")[0] == [[("kela", False, True)]]
    assert terms("kela OR -lasku x")[0] == [[("kela", False, False)], [("x", False, True)]]


def test_and_is_allowed_and_lower_case_operators_are_words():
    assert terms("kela AND lasku") == terms("kela lasku")
    assert parse("cats and dogs or not") == ("cats and dogs or not", [])
    assert parse('"OR" x') == ("OR x", [])


def test_not_before_a_filter_negates_it():
    assert parse("NOT tag:paid") == ("", [("tag", "paid", True)])


def test_an_unquoted_comma_list_is_any_of_its_values():
    (f,) = parse_query("type:PDF,.docx,").filters
    assert f.values == ("pdf", "docx") and f.value == "pdf,docx"
    (f,) = parse_query('in:"Bills, 2026"').filters  # quoted: the comma is part of the name
    assert f.values == ("Bills, 2026",)
    (f,) = parse_query("tag:a,a").filters
    assert f.values == ("a",) and f.any_of == ()
    with pytest.raises(QueryError):
        parse_query("is:starred,nope")
    with pytest.raises(QueryError):
        parse_query("tag:,")


def test_format_filter_keeps_a_list_and_quotes_a_comma_name():
    (f,) = parse_query("-type:pdf,docx").filters
    assert format_filter(f) == "-type:pdf,docx"
    assert format_filter(Filter("in", "Bills,2026")) == 'in:"Bills,2026"'
