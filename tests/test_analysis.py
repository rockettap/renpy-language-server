"""Tests for logical lines and the block tree."""

from renpy_language_server.analysis import Analysis, Block, analyze

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
    if x:
        e "Hi."
    return
"""


def test_logical_lines_and_block_extents() -> None:
    result = analyze(MENU)

    assert result.indent_unit == 4
    assert (result.blocks[0].line.start_line, result.blocks[0].end_line) == (0, 8)
    assert (result.blocks[2].line.start_line, result.blocks[2].end_line) == (2, 4)
    assert (result.blocks[3].line.start_line, result.blocks[3].end_line) == (6, 8)
    assert result.blocks[2].parent is result.blocks[1]
    assert result.blocks[1].parent is result.blocks[0]


def block_at(result: Analysis, line: int) -> Block:
    block = result.block_at(line)
    assert block is not None
    return block


def label_at(result: Analysis, line: int) -> Block:
    block = result.enclosing_label(line)
    assert block is not None
    return block


def test_block_at_returns_the_innermost_block() -> None:
    result = analyze(MENU)

    assert block_at(result, 4).line.start_line == 2
    assert block_at(result, 8).line.start_line == 6
    assert result.block_at(9) is None


def test_enclosing_label() -> None:
    result = analyze(MENU)

    assert label_at(result, 4).line.start_line == 0
    assert label_at(result, 13).line.start_line == 10
    assert result.enclosing_label(14) is None


def test_line_at_handles_continuations() -> None:
    source = "label start:\n    $ x = func(\n        1,\n    )\n    return\n"
    result = analyze(source)

    line = result.line_at(2)
    assert line is not None
    assert (line.start_line, line.end_line) == (1, 3)
    last = result.line_at(4)
    assert last is not None
    assert last.text == "return"


def test_multiline_string_is_one_logical_line() -> None:
    source = 'label start:\n    e """\nnot a block:\n    """\n    return\n'
    result = analyze(source)

    assert [(item.line.start_line, item.end_line) for item in result.blocks] == [(0, 4)]
    assert [item.opens_block for item in result.lines] == [True, False, False, False]


def test_comments_ending_with_colon_do_not_open_blocks() -> None:
    source = 'label start:\n    # note:\n    e "Hi."\n    return\n'
    result = analyze(source)

    assert len(result.blocks) == 1
    assert result.blocks[0].end_line == 3


def test_comment_at_dedent_closes_the_previous_block() -> None:
    source = 'label start:\n    e "Hi."\n# next\nlabel next:\n    return\n'
    result = analyze(source)

    assert result.blocks[0].end_line == 1
    assert result.blocks[1].end_line == 4


def test_empty_block_has_no_body() -> None:
    source = "label start:\nlabel next:\n    return\n"
    result = analyze(source)

    assert (result.blocks[0].line.start_line, result.blocks[0].end_line) == (0, 0)


def test_crlf_and_tabs() -> None:
    source = "label start:\r\n\tif x:\r\n\t\treturn\r\n"
    result = analyze(source)

    assert result.indent_unit == 4
    assert [(item.line.start_line, item.end_line) for item in result.blocks] == [
        (0, 2),
        (1, 2),
    ]


def test_malformed_dedent_does_not_raise() -> None:
    source = 'label start:\n        e "Hi."\n  return\n'
    result = analyze(source)

    assert result.lines
    assert result.blocks
