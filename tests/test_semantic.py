"""Tests for semantic token generation and encoding."""

from itertools import pairwise

from lsprotocol import types

from renpy_language_server.semantic import TOKEN_MODIFIERS, TOKEN_TYPES, semantic_tokens


def _decode(tokens: types.SemanticTokens) -> list[tuple[int, int, int, str, list[str]]]:
    data = tokens.data
    result: list[tuple[int, int, int, str, list[str]]] = []
    line = 0
    start = 0
    for index in range(0, len(data), 5):
        delta_line, delta_start, length, token_type, modifiers = data[index : index + 5]
        line += delta_line
        start = start + delta_start if delta_line == 0 else delta_start
        names = [
            name for bit, name in enumerate(TOKEN_MODIFIERS) if modifiers & (1 << bit)
        ]
        result.append((line, start, length, TOKEN_TYPES[token_type], names))
    return result


SOURCE = """\
define e = Character("Eileen")
image bg room = "bg room.png"
screen stats():
    text "Value"
label chapter:
    e "Hello"
    jump .next
label .next:
    return
"""


def test_disabled_returns_an_empty_stream() -> None:
    assert semantic_tokens("file:///script.rpy", SOURCE, enabled=False).data == []


def test_declarations_and_references() -> None:
    tokens = _decode(semantic_tokens("file:///script.rpy", SOURCE))
    assert (0, 7, 1, "variable", ["declaration"]) in tokens
    assert (1, 6, 7, "variable", ["declaration"]) in tokens
    assert (2, 7, 5, "class", ["declaration"]) in tokens
    assert (4, 6, 7, "function", ["declaration"]) in tokens
    assert (5, 4, 1, "variable", []) in tokens
    assert (6, 9, 5, "function", []) in tokens
    assert (7, 6, 5, "function", ["declaration"]) in tokens


def test_keywords_builtins_and_deprecated_apis() -> None:
    source = (
        'define e = Character("Eileen")\n'
        "$ renpy.pause(0.1)\n"
        '$ Tooltip("old")\n'
        '$ ui.text("old")\n'
    )
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    assert (0, 0, 6, "keyword", []) in tokens
    assert (0, 11, 9, "function", ["defaultLibrary"]) in tokens
    assert (1, 2, 11, "function", ["defaultLibrary"]) in tokens
    assert (2, 2, 7, "class", ["defaultLibrary", "deprecated"]) in tokens
    assert (3, 2, 7, "function", ["defaultLibrary", "deprecated"]) in tokens
    assert (1, 14, 3, "number", []) in tokens


def test_strings_and_comments() -> None:
    source = 'label start:\n    e "renpy.pause"\n    # renpy.pause\n'
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    assert (1, 6, 13, "string", []) in tokens
    assert not any(
        line == 2 and token_type == "function" for line, _, _, token_type, _ in tokens
    )
    assert not any(line == 1 and start == 7 for line, start, _, _, _ in tokens)


def test_parameters_are_tokens() -> None:
    source = "label start(name, count=1):\n    return\n"
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    assert (0, 12, 4, "parameter", ["declaration"]) in tokens
    assert (0, 18, 5, "parameter", ["declaration"]) in tokens


def test_python_class_method_and_definition_modifier() -> None:
    source = (
        "init python:\n    class Player:\n        def hurt(self):\n            return\n"
    )
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    assert (1, 10, 6, "class", ["declaration", "definition"]) in tokens
    assert (2, 12, 4, "function", ["declaration", "definition"]) in tokens
    assert (2, 17, 4, "parameter", ["declaration"]) in tokens


def test_utf16_columns_after_emoji() -> None:
    source = "😀 renpy.pause(1)\n"
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    token = next(item for item in tokens if item[3] == "function")
    assert token[1] == 3


def test_crlf_does_not_shift_lines() -> None:
    source = "label start:\r\n    renpy.pause(1)\r\n"
    tokens = _decode(semantic_tokens("file:///script.rpy", source))
    assert (1, 4, 11, "function", ["defaultLibrary"]) in tokens


def test_tokens_do_not_overlap_on_the_same_line() -> None:
    tokens = _decode(semantic_tokens("file:///script.rpy", SOURCE))
    for previous, current in pairwise(tokens):
        if previous[0] == current[0]:
            assert previous[1] + previous[2] <= current[1]
