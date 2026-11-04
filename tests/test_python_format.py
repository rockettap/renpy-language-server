"""Tests for optional Ruff formatting of python: blocks."""

from renpy_language_server.formatter import FormatOptions, format_source
from renpy_language_server.python_format import format_python_blocks


def test_ruff_formats_a_python_block() -> None:
    source = "python:\n    values=[1,2 ,3]\n"
    result = format_python_blocks(source)

    assert result == "python:\n    values = [1, 2, 3]\n"


def test_ruff_formats_nested_functions() -> None:
    source = "python:\n    def f(a,b):\n        return a+b\n"
    result = format_python_blocks(source)

    assert result == "python:\n    def f(a, b):\n        return a + b\n"


def test_dedent_and_reindent_are_balanced() -> None:
    seen: dict[str, str] = {}

    def runner(code: str) -> str:
        seen["code"] = code
        return "x = 1\n"

    source = "label start:\n    python:\n        x=1\n"
    result = format_python_blocks(source, runner)

    assert seen["code"] == "x=1\n"
    assert result == "label start:\n    python:\n        x = 1\n"


def test_missing_ruff_is_a_no_op() -> None:
    source = "python:\n    x=1\n"
    assert format_python_blocks(source, lambda _: None) == source


def test_invalid_python_is_left_untouched() -> None:
    source = "python:\n    if :\n"
    assert format_python_blocks(source) == source


def test_crlf_is_preserved() -> None:
    source = "python:\r\n    values=[1,2]\r\n"
    result = format_python_blocks(source)

    assert result == "python:\r\n    values = [1, 2]\r\n"


def test_formatter_option_enables_ruff() -> None:
    source = "python:\n    values=[1,2 ,3]\n"
    result = format_source(source, FormatOptions(format_python=True))

    assert result == "python:\n    values = [1, 2, 3]\n"


def test_formatter_option_is_off_by_default() -> None:
    source = "python:\n    values=[1,2 ,3]\n"
    # Inline spacing still runs; Ruff's list spacing does not.
    assert format_source(source) == "python:\n    values = [1,2 ,3]\n"
