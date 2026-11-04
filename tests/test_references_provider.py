"""Tests for the find-references provider."""

from lsprotocol import types

from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.references import references_at

URI = "file:///script0.rpy"


def _index(*sources: str) -> WorkspaceIndex:
    workspace = WorkspaceIndex()
    for number, source in enumerate(sources):
        workspace.update(f"file:///script{number}.rpy", source)
    return workspace


def _ranges(locations: list[types.Location]) -> list[tuple[str, int, int, int]]:
    return [
        (
            item.uri,
            item.range.start.line,
            item.range.start.character,
            item.range.end.character,
        )
        for item in locations
    ]


def test_references_include_declarations_and_uses() -> None:
    source = "label start:\n    jump target\n\nlabel target:\n    return\n"
    index = _index(source)

    found = references_at(URI, source, 1, 10, index)
    assert _ranges(found) == [
        (URI, 1, 9, 15),
        (URI, 3, 6, 12),
    ]


def test_references_can_exclude_declarations() -> None:
    source = "label start:\n    jump target\n\nlabel target:\n    return\n"
    index = _index(source)

    found = references_at(URI, source, 1, 10, index, include_declaration=False)
    assert _ranges(found) == [(URI, 1, 9, 15)]


def test_references_are_cross_file() -> None:
    first = "label start:\n    jump target\n"
    second = "label target:\n    return\n"
    index = _index(first, second)

    found = references_at(URI, first, 1, 10, index)
    assert _ranges(found) == [
        (URI, 1, 9, 15),
        ("file:///script1.rpy", 0, 6, 12),
    ]


def test_local_label_references_include_both_written_forms() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "    jump chapter.intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
    )
    index = _index(source)

    found = references_at(URI, source, 4, 7, index)
    assert _ranges(found) == [
        (URI, 1, 9, 15),
        (URI, 2, 9, 22),
        (URI, 4, 6, 12),
    ]


def test_unknown_positions_return_no_references() -> None:
    source = "label start:\n    jump start\n"
    index = _index(source)

    assert references_at(URI, source, 0, 0, index) == []
    assert references_at(URI, source, 99, 0, index) == []


def test_variable_reference_columns_are_utf16() -> None:
    source = 'define foo = 1\nlabel start:\n    e "😀 [foo]"\n'
    index = _index(source)

    # Callers pass server (code point) positions; locations use UTF-16.
    found = references_at(URI, source, 2, 10, index)
    assert _ranges(found) == [
        (URI, 0, 7, 10),
        (URI, 2, 11, 14),
    ]
