"""Tests for jump/call target resolution."""

from pathlib import Path

from renpy_language_server.assets import Asset, AssetIndex
from renpy_language_server.definition import (
    find_definition,
    find_image_definition,
    find_target,
    target_at_position,
)
from renpy_language_server.index import WorkspaceIndex


def index_with(*sources: str) -> WorkspaceIndex:
    index = WorkspaceIndex()
    for number, source in enumerate(sources):
        index.update(f"file:///script{number}.rpy", source)
    return index


def test_find_target() -> None:
    target = find_target("    jump chapter_one")
    assert target is not None
    assert (target.name, target.start, target.end) == ("chapter_one", 9, 20)


def test_call_target_ignores_arguments_and_from_clause() -> None:
    target = find_target("    call chapter_one(arg=1) from _call_chapter_one")
    assert target is not None
    assert target.name == "chapter_one"


def test_dynamic_and_screen_targets_are_ignored() -> None:
    assert find_target("    call screen main_menu") is None
    assert find_target("    jump expression target") is None
    assert find_target("    jump 'chapter_one'") is None
    assert find_target('    e "jump chapter_one"') is None


def test_target_at_position_only_matches_the_target() -> None:
    assert target_at_position("    jump chapter_one", 10) is not None
    assert target_at_position("    jump chapter_one", 2) is None


def test_definition_in_the_same_file() -> None:
    source = "label start:\n    jump chapter_one\n\nlabel chapter_one:\n    return\n"
    index = index_with(source)
    symbols = find_definition(source, 1, 10, index)

    assert len(symbols) == 1
    assert symbols[0].line == 3


def test_definition_across_files() -> None:
    index = index_with(
        "label start:\n    call chapter_one\n",
        "label chapter_one:\n    return\n",
    )
    symbols = find_definition("label start:\n    call chapter_one\n", 1, 10, index)

    assert len(symbols) == 1
    assert symbols[0].uri == "file:///script1.rpy"


def test_dotted_label() -> None:
    source = "label chapter.one:\n    return\nlabel start:\n    jump chapter.one\n"
    index = index_with(source)
    symbols = find_definition(source, 3, 10, index)

    assert len(symbols) == 1
    assert symbols[0].name == "chapter.one"


def test_unknown_and_dynamic_targets_return_nothing() -> None:
    source = "label start:\n    jump missing\n    jump expression x\n"
    index = index_with(source)
    assert find_definition(source, 1, 10, index) == []
    assert find_definition(source, 2, 10, index) == []


def test_cursor_outside_the_target_returns_nothing() -> None:
    source = "label start:\n    jump chapter_one\nlabel chapter_one:\n    return\n"
    index = index_with(source)
    assert find_definition(source, 1, 2, index) == []


def test_local_target_resolves_under_the_enclosing_global_label() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "\n"
        "label other:\n"
        "    jump .intro\n"
        "\n"
        "label chapter.intro:\n"
        "    return\n"
        "\n"
        "label other.intro:\n"
        "    return\n"
    )
    index = index_with(source)

    chapter = find_definition(source, 1, 10, index)
    other = find_definition(source, 4, 10, index)

    assert len(chapter) == 1
    assert chapter[0].name == "chapter.intro"
    assert chapter[0].line == 6
    assert len(other) == 1
    assert other[0].name == "other.intro"
    assert other[0].line == 9


def test_full_name_local_target_resolves() -> None:
    source = (
        "label start:\n"
        "    jump chapter.intro\n"
        "\n"
        "label chapter:\n"
        "    return\n"
        "\n"
        "label .intro:\n"
        "    return\n"
    )
    index = index_with(source)
    symbols = find_definition(source, 1, 10, index)

    assert len(symbols) == 1
    assert symbols[0].name == "chapter.intro"


def test_image_definition_for_an_automatic_image(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg room.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])
    source = "label start:\n    show bg room\n"
    index = index_with(source)

    found = find_image_definition(source, 1, 11, index, assets)
    assert isinstance(found, Asset)
    assert found.path == image


def test_declared_image_wins_over_an_automatic_asset(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])
    source = 'image bg = "bg.png"\nlabel start:\n    show bg\n'
    index = index_with(source)

    found = find_image_definition(source, 2, 11, index, assets)
    assert not isinstance(found, Asset)
    assert found is not None
    assert found.line == 0


def test_image_definition_ignores_other_positions(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])
    source = 'image bg = "bg.png"\nlabel start:\n    show bg\n'
    index = index_with(source)

    assert find_image_definition(source, 0, 7, index, assets) is None
    assert find_image_definition(source, 1, 11, index, assets) is None
    assert find_image_definition(source, 9, 0, index, assets) is None


def test_definition_for_a_screen_reference() -> None:
    source = (
        "screen stats():\n"
        "    pass\n"
        "\n"
        "label start:\n"
        "    use stats\n"
        "    call screen stats\n"
    )
    index = index_with(source)

    for line, character in ((4, 8), (5, 16)):
        symbols = find_definition(source, line, character, index)
        assert len(symbols) == 1
        assert symbols[0].kind == "screen"
        assert symbols[0].line == 0


def test_definition_for_transform_image_character_and_style() -> None:
    source = (
        "transform bounce:\n"
        "    xoffset 0\n"
        "\n"
        'image bg room = "bg.png"\n'
        "\n"
        "layeredimage eileen:\n"
        '    always "base"\n'
        "\n"
        'define e = Character("Eileen")\n'
        "\n"
        "style dark:\n"
        '    color "#000"\n'
        "\n"
        "style light is dark:\n"
        '    color "#fff"\n'
        "\n"
        "label start:\n"
        "    show bg room at bounce\n"
        "    show eileen\n"
        '    e "Hi"\n'
    )
    index = index_with(source)

    cases = (
        (17, 21, "transform", 0),
        (17, 11, "image", 3),
        (18, 11, "layeredimage", 5),
        (19, 5, "character", 8),
        (13, 17, "style", 10),
    )
    for line, character, kind, expected_line in cases:
        symbols = find_definition(source, line, character, index)
        assert len(symbols) == 1
        assert symbols[0].kind == kind
        assert symbols[0].line == expected_line


def test_definition_for_a_variable_declaration_and_use() -> None:
    source = "define foo = 1\nlabel start:\n    $ foo += 1\n"
    index = index_with(source)

    declaration = find_definition(source, 0, 7, index)
    use = find_definition(source, 2, 6, index)
    assert [item.kind for item in declaration] == ["variable"]
    assert [item.kind for item in use] == ["variable"]
    assert use[0].line == 0


def test_definition_does_not_fabricate_builtin_locations() -> None:
    source = "label start:\n    renpy.pause(1.0)\n"
    index = index_with(source)

    assert find_definition(source, 1, 6, index) == []


def test_member_definition_from_self_attribute() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def heal(self):\n"
        "            self.hp += 1\n"
    )
    index = index_with(source)
    symbols = find_definition(source, 5, 18, index)

    assert [(item.kind, item.name, item.line) for item in symbols] == [
        ("field", "hp", 2)
    ]


def test_member_definition_from_class_attribute() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "label start:\n"
        "    $ Player.hp = 1\n"
    )
    index = index_with(source)
    symbols = find_definition(source, 5, 15, index)

    assert [(item.kind, item.name, item.line) for item in symbols] == [
        ("field", "hp", 2)
    ]


def test_persistent_definition() -> None:
    source = (
        "define persistent.score = 0\n\nlabel start:\n    $ persistent.score += 1\n"
    )
    index = index_with(source)
    character = source.splitlines()[3].index("score") + 1
    symbols = find_definition(source, 3, character, index)

    assert [(item.kind, item.name, item.line) for item in symbols] == [
        ("persistent", "score", 0)
    ]


def test_store_attribute_definition() -> None:
    source = "default gold = 0\n\nlabel start:\n    $ store.gold += 1\n"
    index = index_with(source)
    character = source.splitlines()[3].index("gold") + 1
    symbols = find_definition(source, 3, character, index)

    assert [(item.kind, item.name, item.line) for item in symbols] == [
        ("variable", "gold", 0)
    ]


def test_class_base_definition() -> None:
    source = (
        "init python:\n"
        "    class Base:\n"
        "        pass\n"
        "\n"
        "    class Player(Base):\n"
        "        pass\n"
    )
    index = index_with(source)
    symbols = find_definition(source, 4, 18, index)

    assert [(item.kind, item.name, item.line) for item in symbols] == [
        ("class", "Base", 1)
    ]
