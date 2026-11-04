"""Tests for inline spacing in Python-ish Ren'Py statements."""

from renpy_language_server.formatter import FormatOptions, format_source
from renpy_language_server.spacing import (
    normalize_python_spacing,
    normalize_statement_spacing,
)


def test_dollar_assignment() -> None:
    assert normalize_statement_spacing("$ points=1") == "$ points = 1"


def test_define_and_default() -> None:
    assert (
        normalize_statement_spacing('define e=Character("Eileen")')
        == 'define e = Character("Eileen")'
    )
    assert normalize_statement_spacing("default points=0") == "default points = 0"


def test_conditionals_and_loops() -> None:
    assert normalize_statement_spacing("if points==1:") == "if points == 1:"
    assert normalize_statement_spacing("elif x!=y:") == "elif x != y:"
    assert normalize_statement_spacing("while x<=10:") == "while x <= 10:"
    assert normalize_statement_spacing("assert x>=1") == "assert x >= 1"


def test_assignment_operators() -> None:
    assert normalize_statement_spacing("$ x+=1") == "$ x += 1"
    assert normalize_statement_spacing("$ x**=2") == "$ x **= 2"


def test_strings_comments_and_keyword_arguments_are_untouched() -> None:
    assert normalize_statement_spacing('$ x = "a=b"') == '$ x = "a=b"'
    assert (
        normalize_statement_spacing('$ x = Character("A", color="#fff")')
        == '$ x = Character("A", color="#fff")'
    )
    assert normalize_statement_spacing("$ x=1  # note x=2") == "$ x = 1  # note x=2"


def test_non_python_lines_are_untouched() -> None:
    for line in (
        'e "Score=1"',
        'text "Score=1"',
        "show eileen happy at center",
        "linear 0.4 xoffset=0",
        "screen main_menu():",
    ):
        assert normalize_statement_spacing(line) == line


def test_formatter_applies_spacing() -> None:
    source = "$ points=1\n"
    assert format_source(source) == "$ points = 1\n"


def test_formatter_spacing_can_be_disabled() -> None:
    source = "$ points=1\n"
    options = FormatOptions(normalize_spacing=False)
    assert format_source(source, options) == source


def test_operator_at_line_end_does_not_leave_trailing_space() -> None:
    assert normalize_statement_spacing("$ x=") == "$ x ="
    assert format_source("$ x=\n") == "$ x =\n"


def test_python_arithmetic_operators() -> None:
    assert normalize_python_spacing("x=1+2*3") == "x = 1 + 2 * 3"
    assert normalize_python_spacing("a**b") == "a ** b"
    assert normalize_python_spacing("a//b") == "a // b"
    assert normalize_python_spacing("a<<2|b&c") == "a << 2 | b & c"
    assert normalize_python_spacing("x = a @ b") == "x = a @ b"


def test_python_unary_operators_are_untouched() -> None:
    for line in (
        "return -1",
        "yield -x",
        "x = not -1",
        "x = (-1)",
        "print(-1)",
        "if -x:",
        "x = 1 if a else -1",
        "a - -b",
    ):
        assert normalize_python_spacing(line) == line


def test_python_slices_arguments_and_keyword_arguments_are_untouched() -> None:
    for line in (
        "z = a[1:2]",
        "z = a[::2]",
        "f(*args, **kwargs)",
        "f(x=1, color='#fff')",
        "d = {'a': 1}",
        "@decorator",
    ):
        assert normalize_python_spacing(line) == line


def test_keyword_arguments_lose_spaces_around_equals() -> None:
    assert (
        normalize_statement_spacing('$ pv = Character(u"A", color = "#00B7EB")')
        == '$ pv = Character(u"A", color="#00B7EB")'
    )
    assert (
        normalize_statement_spacing('$ x = outer(inner(a = 1), b = "c=d")')
        == '$ x = outer(inner(a=1), b="c=d")'
    )
    assert (
        normalize_statement_spacing("$ x = f(a = 1)  # note b = 2")
        == "$ x = f(a=1)  # note b = 2"
    )
    assert normalize_statement_spacing("if f(a = 1) == 2:") == "if f(a=1) == 2:"
    assert normalize_python_spacing("f(x = 1, color = '#fff')") == (
        "f(x=1, color='#fff')"
    )
    assert normalize_python_spacing("def f(a = 1):") == "def f(a=1):"


def test_assignments_keep_spaces_around_equals() -> None:
    assert normalize_statement_spacing("$ x = f(y=1)") == "$ x = f(y=1)"
    assert normalize_statement_spacing("$ x += 1") == "$ x += 1"
    assert normalize_python_spacing("x = 1") == "x = 1"


def test_python_comments_and_strings_are_untouched() -> None:
    assert normalize_python_spacing('s = "a+b"') == 's = "a+b"'
    assert normalize_python_spacing("x = 1  # a+b") == "x = 1  # a+b"


def test_formatter_normalizes_python_blocks() -> None:
    source = "python:\n    x=1+2*3\n    y = -1\n    f(x=1, *args)\n"
    expected = "python:\n    x = 1 + 2 * 3\n    y = -1\n    f(x=1, *args)\n"
    assert format_source(source) == expected


def test_init_python_blocks_are_normalized() -> None:
    source = "init python:\n    total=sum(values)\n"
    assert format_source(source) == "init python:\n    total = sum(values)\n"


def test_python_spacing_is_idempotent() -> None:
    source = "python:\n    x=1+2*3\n"
    once = format_source(source)
    assert format_source(once) == once
