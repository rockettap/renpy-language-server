"""Tests for single-to-double quote normalization."""

from renpy_language_server.formatter import FormatOptions, format_source
from renpy_language_server.quotes import normalize_quotes


def test_simple_strings_are_rewritten() -> None:
    assert normalize_quotes("x = 'value'") == 'x = "value"'
    assert normalize_quotes("e 'Hello'") == 'e "Hello"'
    assert normalize_quotes("text 'Points' size 20") == 'text "Points" size 20'
    assert normalize_quotes("@'icon.png'") == '@"icon.png"'


def test_color_literals_are_rewritten() -> None:
    assert normalize_quotes("define gui.accent = '#99ccff'") == (
        'define gui.accent = "#99ccff"'
    )
    assert normalize_quotes("text \"x\" color '#fff'") == 'text "x" color "#fff"'


def test_double_quoted_strings_are_untouched() -> None:
    source = 'x = "it\'s fine"\n'
    assert normalize_quotes(source) == source


def test_strings_with_unescaped_double_quotes_are_untouched() -> None:
    for source in (
        """x = 'He said "hi"'""",
        """x = '''He said "hi"'''""",
        """x = f'{d["k"]}'""",
    ):
        assert normalize_quotes(source) == source


def test_escaped_double_quotes_still_convert() -> None:
    assert normalize_quotes(r"""x = 'He said \"hi\"'""") == (
        r'''x = "He said \"hi\""'''
    )


def test_escaped_single_quote_is_kept() -> None:
    assert normalize_quotes(r"""x = 'it\'s'""") == r'''x = "it\'s"'''


def test_triple_quoted_strings_convert() -> None:
    assert normalize_quotes("x = '''line one\nline two'''") == (
        'x = """line one\nline two"""'
    )
    assert normalize_quotes("'''text'''") == '"""text"""'


def test_comments_are_untouched() -> None:
    source = "x = 'a'  # 'comment' and \"quotes\"\n#'another'\n"
    assert (
        normalize_quotes(source)
        == "x = \"a\"  # 'comment' and \"quotes\"\n#'another'\n"
    )


def test_hashes_inside_strings_are_preserved() -> None:
    assert normalize_quotes("x = 'a # b'") == 'x = "a # b"'


def test_string_prefixes_are_kept() -> None:
    assert normalize_quotes("x = u'a'") == 'x = u"a"'
    assert normalize_quotes(r"x = r'a\n'") == r'x = r"a\n"'
    assert normalize_quotes("x = f'{value}'") == 'x = f"{value}"'
    assert normalize_quotes("x = rf'{value}'") == 'x = rf"{value}"'


def test_fstring_nested_strings_do_not_end_the_literal_early() -> None:
    assert normalize_quotes("x = f'{d['k']}'") == "x = f\"{d['k']}\""
    unchanged = "x = f'{f(a=\"b\")}'"
    assert normalize_quotes(unchanged) == unchanged


def test_unterminated_string_leaves_the_rest_untouched() -> None:
    assert normalize_quotes("a = 'x'\nb = 'y") == 'a = "x"\nb = \'y'
    assert normalize_quotes("b = 'y") == "b = 'y"


def test_multiline_single_quoted_string_converts() -> None:
    assert normalize_quotes("e 'first\nsecond'\n") == 'e "first\nsecond"\n'


def test_line_restriction_keeps_literals_outside_the_range() -> None:
    source = "a = 'one'\nb = 'two'\n"
    assert normalize_quotes(source, {0}) == "a = \"one\"\nb = 'two'\n"
    assert normalize_quotes(source, {1}) == "a = 'one'\nb = \"two\"\n"
    assert normalize_quotes(source, set()) == source


def test_line_restriction_converts_multiline_literals_atomically() -> None:
    source = "e 'first\nsecond'\nnext 'x'\n"
    assert normalize_quotes(source, {0}) == source
    assert normalize_quotes(source, {1}) == source
    assert normalize_quotes(source, {0, 1}) == "e \"first\nsecond\"\nnext 'x'\n"
    assert normalize_quotes(source, range(2)) == ("e \"first\nsecond\"\nnext 'x'\n")


def test_line_restriction_does_not_drop_the_rest_of_the_file() -> None:
    source = "a = 'one'\nb = 'two'\n"
    # A gap in the allowed lines still allows a single-line literal whose two
    # delimiters are both on an allowed line.
    assert normalize_quotes(source, {0, 2}) == "a = \"one\"\nb = 'two'\n"


def test_normalization_is_idempotent() -> None:
    source = "define gui.accent = '#99ccff'\ne 'Hello'\n"
    once = normalize_quotes(source)
    assert normalize_quotes(once) == once


def test_formatter_applies_and_can_disable_quote_normalization() -> None:
    source = "define accent = '#99ccff'\n"
    assert format_source(source) == 'define accent = "#99ccff"\n'
    assert format_source(source, FormatOptions(normalize_quotes=False)) == source
