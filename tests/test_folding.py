"""Tests for explicit Ren'Py folding ranges."""

from renpy_language_server.folding import folding_ranges

MENU = """\
label start:
    menu:
        "1":
            e "First."
            jump one

        "2":
            e "Second."
            jump two

label one:
    return

label two:
    return
"""


def ranges(source: str) -> list[tuple[int, int]]:
    return [(item.start_line, item.end_line) for item in folding_ranges(source)]


def test_menu_choices_fold_independently() -> None:
    assert ranges(MENU) == [
        (0, 8),
        (1, 8),
        (2, 4),
        (6, 8),
        (10, 11),
        (13, 14),
    ]


def test_trailing_blank_lines_are_not_folded() -> None:
    result = ranges(MENU)
    assert (2, 4) in result
    assert (2, 5) not in result
    assert (6, 8) in result
    assert (6, 9) not in result


def test_nested_blocks_have_nested_ranges() -> None:
    source = 'label start:\n    if x:\n        e "Hello."\n    return\n'
    assert ranges(source) == [(0, 3), (1, 2)]


def test_multiline_string_does_not_create_or_break_folds() -> None:
    source = 'label start:\n    e """\nnot a block:\n    """\n    return\n'
    assert ranges(source) == [(0, 4)]


def test_bracket_continuation_does_not_create_a_fold() -> None:
    source = (
        "label start:\n    $ x = func(\n        1,\n        2,\n    )\n    return\n"
    )
    assert ranges(source) == [(0, 5)]


def test_dialogue_ending_with_colon_is_not_an_opener() -> None:
    source = 'label start:\n    e "Look:"\n    return\n'
    assert ranges(source) == [(0, 2)]


def test_comment_ending_with_colon_is_not_an_opener() -> None:
    source = 'label start:\n    # note:\n    e "Hello."\n    return\n'
    assert ranges(source) == [(0, 3)]


def test_empty_block_has_no_range() -> None:
    source = "label start:\nlabel next:\n    return\n"
    assert ranges(source) == [(1, 2)]


def test_crlf_is_supported() -> None:
    assert ranges(MENU.replace("\n", "\r\n")) == ranges(MENU)
