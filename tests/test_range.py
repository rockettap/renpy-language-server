"""Tests for range formatting."""

from renpy_language_server.edits import apply_edits, compute_edits_in_range
from renpy_language_server.formatter import format_source

SOURCE = 'label a:\n  e "A"\n\nlabel b:\n  e "B"\n'


def test_range_edits_only_touch_the_selected_block() -> None:
    formatted = format_source(SOURCE)
    edits = compute_edits_in_range(SOURCE, formatted, 1, 1)
    result = apply_edits(SOURCE, edits)

    assert result == 'label a:\n    e "A"\n\nlabel b:\n  e "B"\n'


def test_second_block_can_be_formatted_alone() -> None:
    formatted = format_source(SOURCE)
    edits = compute_edits_in_range(SOURCE, formatted, 4, 4)
    result = apply_edits(SOURCE, edits)

    assert result == 'label a:\n  e "A"\n\nlabel b:\n    e "B"\n'


def test_empty_range_returns_no_edits_when_nothing_would_change() -> None:
    formatted = 'label a:\n    e "A"\n'
    assert compute_edits_in_range(formatted, formatted, 0, 1) == []


def test_crlf_is_preserved() -> None:
    source = SOURCE.replace("\n", "\r\n")
    formatted = format_source(source)
    edits = compute_edits_in_range(source, formatted, 1, 1)
    result = apply_edits(source, edits)

    assert result == 'label a:\r\n    e "A"\r\n\r\nlabel b:\r\n  e "B"\r\n'
