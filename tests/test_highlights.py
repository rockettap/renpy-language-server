"""Tests for LSP document highlights used for occurrence shading."""

from lsprotocol import types

from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.rename import document_highlights_at

_URI = "file:///script0.rpy"


def _index(*sources: str) -> WorkspaceIndex:
    workspace = WorkspaceIndex()
    for number, source in enumerate(sources):
        workspace.update(f"file:///script{number}.rpy", source)
    return workspace


def _highlights(
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex | None = None,
) -> list[tuple[int, int, int, types.DocumentHighlightKind]]:
    found = document_highlights_at(
        _URI,
        source,
        line,
        character,
        index if index is not None else _index(source),
    )
    assert found is not None
    result: list[tuple[int, int, int, types.DocumentHighlightKind]] = []
    for item in found:
        assert item.kind is not None
        result.append(
            (
                item.range.start.line,
                item.range.start.character,
                item.range.end.character,
                item.kind,
            )
        )
    return result


def test_variable_highlights_include_declaration_use_and_interpolation() -> None:
    source = (
        'define ambience = "a.mp3"\n'
        "label start:\n"
        "    play music ambience\n"
        '    e "[ambience]"\n'
    )

    assert _highlights(source, 0, 8) == [
        (0, 7, 15, types.DocumentHighlightKind.Write),
        (2, 15, 23, types.DocumentHighlightKind.Read),
        (3, 8, 16, types.DocumentHighlightKind.Read),
    ]


def test_variable_highlights_work_from_a_use_and_stay_in_the_open_document() -> None:
    first = 'define ambience = "a.mp3"\nlabel start:\n    play music ambience\n'
    second = "label other:\n    play music ambience\n"
    index = _index(first, second)

    assert _highlights(first, 2, 18, index) == [
        (0, 7, 15, types.DocumentHighlightKind.Write),
        (2, 15, 23, types.DocumentHighlightKind.Read),
    ]


def test_global_label_highlights_match_rename_scope() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "    jump chapter.intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
        "\n"
        "label chapter.extra:\n"
        "    return\n"
    )

    assert _highlights(source, 0, 7) == [
        (0, 6, 13, types.DocumentHighlightKind.Write),
        (2, 9, 22, types.DocumentHighlightKind.Read),
        (7, 6, 19, types.DocumentHighlightKind.Write),
    ]


def test_screen_highlights_include_all_screen_statements() -> None:
    source = (
        "screen stats():\n"
        '    text "Hi"\n'
        "\n"
        "label start:\n"
        "    use stats\n"
        "    call screen stats\n"
    )

    assert _highlights(source, 0, 7) == [
        (0, 7, 12, types.DocumentHighlightKind.Write),
        (4, 8, 13, types.DocumentHighlightKind.Read),
        (5, 16, 21, types.DocumentHighlightKind.Read),
    ]


def test_highlights_refuse_non_symbols() -> None:
    source = "label start:\n    return\n"

    assert document_highlights_at(_URI, source, 1, 5, _index(source)) is None
    assert document_highlights_at(_URI, source, 0, 0, _index(source)) is None
