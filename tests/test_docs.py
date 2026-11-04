"""Tests for comment-block documentation."""

from renpy_language_server.docs import comment_block


def test_collects_a_contiguous_block_above_the_line() -> None:
    lines = [
        "# First line.",
        "#",
        "#   Indented detail.",
        "label start:",
    ]

    assert comment_block(lines, 3) == "First line.\n\nIndented detail."


def test_stops_at_a_non_comment_line() -> None:
    lines = [
        "# Far away.",
        "",
        "# Closest.",
        "label start:",
    ]

    assert comment_block(lines, 3) == "Closest."


def test_returns_empty_without_a_comment() -> None:
    assert comment_block(["label start:"], 0) == ""
    assert comment_block(["", "label start:"], 1) == ""
    assert comment_block([], 0) == ""


def test_out_of_range_lines_are_safe() -> None:
    assert comment_block(["# Doc.", "label start:"], -1) == ""
    assert comment_block(["# Doc.", "label start:"], 99) == ""
