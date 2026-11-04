"""Tests for the shared symbol resolver."""

import pytest

from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.resolve import (
    declarations,
    locate,
    occurrences,
)
from renpy_language_server.resolve import target as resolve_target

URI = "file:///script0.rpy"


def _index(*sources: str) -> WorkspaceIndex:
    workspace = WorkspaceIndex()
    for number, source in enumerate(sources):
        workspace.update(f"file:///script{number}.rpy", source)
    return workspace


def _resolve(source: str, line: int, character: int, index: WorkspaceIndex):
    located = locate(URI, source, line, character, index)
    assert located is not None
    resolved = resolve_target(located, index)
    assert resolved is not None
    return resolved


@pytest.mark.parametrize(
    (
        "source",
        "decl_line",
        "decl_character",
        "use_line",
        "use_character",
        "family",
        "name",
    ),
    [
        ("label start:\n    jump start\n", 0, 6, 1, 10, "label", "start"),
        (
            "screen stats():\n    pass\n\nlabel start:\n    use stats\n",
            0,
            7,
            4,
            8,
            "screen",
            "stats",
        ),
        (
            "transform bounce:\n    xoffset 0\n\nlabel start:\n    show e at bounce\n",
            0,
            10,
            4,
            14,
            "transform",
            "bounce",
        ),
        (
            'image bg room = "bg.png"\n\nlabel start:\n    show bg room\n',
            0,
            6,
            3,
            9,
            "image",
            "bg room",
        ),
        (
            'layeredimage eileen:\n    always "base"\n\nlabel start:\n    show eileen\n',
            0,
            13,
            4,
            9,
            "image",
            "eileen",
        ),
        (
            'define e = Character("Eileen")\n\nlabel start:\n    e "Hi"\n',
            0,
            7,
            3,
            4,
            "character",
            "e",
        ),
        (
            'style base:\n    color "#fff"\n\nstyle dark is base:\n    color "#000"\n',
            0,
            6,
            3,
            14,
            "style",
            "base",
        ),
        (
            'define ambience = "a.mp3"\n\nlabel start:\n    play music ambience\n',
            0,
            7,
            3,
            15,
            "variable",
            "ambience",
        ),
    ],
)
def test_declaration_and_reference_resolve_to_the_same_family(
    source: str,
    decl_line: int,
    decl_character: int,
    use_line: int,
    use_character: int,
    family: str,
    name: str,
) -> None:
    index = _index(source)
    declaration = _resolve(source, decl_line, decl_character, index)
    assert (declaration.family, declaration.name) == (family, name)

    use = _resolve(source, use_line, use_character, index)
    assert (use.family, use.name) == (family, name)


def test_declarations_include_image_and_layered_image() -> None:
    source = 'layeredimage eileen:\n    always "base"\n\nimage eileen = "eileen.png"\n'
    index = _index(source)

    found = declarations("image", "eileen", index)
    assert {symbol.kind for symbol in found} == {"layeredimage", "image"}


def test_occurrences_are_cross_file_and_mark_writes() -> None:
    index = _index("label start:\n    jump target\n", "label target:\n    return\n")
    source = "label start:\n    jump target\n"

    resolved = _resolve(source, 1, 10, index)
    assert (resolved.family, resolved.name) == ("label", "target")
    assert [
        (item.uri, item.line, item.start, item.end, item.write)
        for item in occurrences(resolved, index)
    ] == [
        ("file:///script0.rpy", 1, 9, 15, False),
        ("file:///script1.rpy", 0, 6, 12, True),
    ]


def test_local_labels_resolve_to_the_qualified_name() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "    jump chapter.intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
    )
    index = _index(source)

    resolved = _resolve(source, 4, 7, index)
    assert resolved.name == "chapter.intro"
    assert [(item.line, item.write) for item in occurrences(resolved, index)] == [
        (1, False),
        (2, False),
        (4, True),
    ]


def test_occurrence_columns_are_utf16() -> None:
    source = 'define foo = 1\nlabel start:\n    e "😀 [foo]"\n'
    index = _index(source)

    # Callers pass server (code point) positions; stored spans are UTF-16.
    resolved = _resolve(source, 2, 10, index)
    use = [item for item in occurrences(resolved, index) if item.line == 2]
    assert [(item.start, item.end) for item in use] == [(11, 14)]


def test_unknown_and_out_of_range_positions_return_nothing() -> None:
    source = "label start:\n    jump start\n"
    index = _index(source)

    assert locate(URI, source, 99, 0, index) is None
    assert locate(URI, source, 0, 999, index) is None
    assert locate(URI, source, 0, 0, index) is None


def test_member_resolution_is_container_aware() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def heal(self):\n"
        "            self.hp += 1\n"
        "\n"
        "    class Enemy:\n"
        "        hp = 5\n"
    )
    index = _index(source)

    resolved = _resolve(source, 5, 18, index)
    assert (resolved.family, resolved.name, resolved.container) == (
        "member",
        "hp",
        "Player",
    )
    found = declarations(resolved.family, resolved.name, index, resolved.container)
    assert [(item.kind, item.container, item.line) for item in found] == [
        ("field", "Player", 2)
    ]
    assert [(item.line, item.write) for item in occurrences(resolved, index)] == [
        (2, True),
        (5, False),
    ]


def test_class_member_reference_resolves() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 1\n"
        "\n"
        "label start:\n"
        "    $ Player.hp = 2\n"
    )
    index = _index(source)

    resolved = _resolve(source, 5, 15, index)
    assert (resolved.family, resolved.container, resolved.name) == (
        "member",
        "Player",
        "hp",
    )
    assert [item.kind for item in declarations("member", "hp", index, "Player")] == [
        "field"
    ]


def test_persistent_resolution_and_occurrences() -> None:
    source = (
        "define persistent.score = 0\n\nlabel start:\n    $ persistent.score += 1\n"
    )
    index = _index(source)
    character = source.splitlines()[3].index("score") + 1

    resolved = _resolve(source, 3, character, index)
    assert (resolved.family, resolved.name, resolved.container) == (
        "persistent",
        "score",
        "persistent",
    )
    assert [(item.line, item.write) for item in occurrences(resolved, index)] == [
        (0, True),
        (3, False),
    ]


def test_store_reference_resolves_to_a_variable() -> None:
    source = "default gold = 0\n\nlabel start:\n    $ store.gold += 1\n"
    index = _index(source)
    character = source.splitlines()[3].index("gold") + 1

    resolved = _resolve(source, 3, character, index)
    assert (resolved.family, resolved.name) == ("variable", "gold")
    assert [(item.line, item.write) for item in occurrences(resolved, index)] == [
        (0, True),
        (3, False),
    ]


def test_attribute_chain_only_resolves_the_first_member() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 1\n"
        "\n"
        "label start:\n"
        "    $ Player.hp.value = 2\n"
    )
    index = _index(source)
    references = [item for item in index.all_references() if item.kind == "member"]

    assert [(item.container, item.name) for item in references] == [("Player", "hp")]


def test_self_attribute_outside_a_class_is_ignored() -> None:
    source = "label start:\n    $ self.hp = 1\n"
    index = _index(source)

    assert [item for item in index.all_references() if item.kind == "member"] == []


def test_member_reference_columns_are_utf16() -> None:
    from renpy_language_server.index import utf16_length

    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 1\n"
        "\n"
        "label start:\n"
        '    $ "\U0001f600"; Player.hp = 2\n'
    )
    index = _index(source)
    reference = next(item for item in index.all_references() if item.kind == "member")

    expected = utf16_length('    $ "\U0001f600"; Player.')
    assert reference.character == expected
