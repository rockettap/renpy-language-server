"""Tests for hover resolution."""

from pathlib import Path

from lsprotocol import types

from renpy_language_server.assets import AssetIndex
from renpy_language_server.hover import hover_at
from renpy_language_server.index import WorkspaceIndex, utf16_length

CURRENT = "file:///script.rpy"


def _workspace(source: str, extra: list[tuple[str, str]] | None = None):
    workspace = WorkspaceIndex()
    for uri, text in extra or []:
        workspace.update(uri, text)
    workspace.update(CURRENT, source)
    return workspace


def _hover(
    source: str,
    line: int,
    character: int,
    *,
    extra: list[tuple[str, str]] | None = None,
    assets: AssetIndex | None = None,
    uri: str = CURRENT,
) -> types.Hover | None:
    workspace = _workspace(source, extra)
    return hover_at(
        uri,
        source,
        line,
        character,
        workspace,
        assets or AssetIndex(),
    )


def _value(hover: types.Hover) -> str:
    contents = hover.contents
    assert isinstance(contents, types.MarkupContent)
    return contents.value


def _range(hover: types.Hover) -> types.Range:
    assert hover.range is not None
    return hover.range


def test_label_declaration_shows_parameters_and_comment_docs() -> None:
    source = "# Starts the game.\nlabel start(name):\n    return\n"

    hover = _hover(source, 1, 7)
    assert hover is not None
    value = _value(hover)
    assert "**label** `start`" in value
    assert "start(name)" in value
    assert "/script.rpy:2" in value
    assert "Starts the game." in value
    assert _range(hover).start.character == 6


def test_jump_reference_resolves_across_files_with_docs(tmp_path: Path) -> None:
    other = tmp_path / "other.rpy"
    other.write_text("# Next chapter.\nlabel next:\n    return\n", encoding="utf-8")
    source = "label start:\n    jump next\n"
    extra = [(other.as_uri(), other.read_text(encoding="utf-8"))]

    hover = _hover(source, 1, 10, extra=extra)
    assert hover is not None
    value = _value(hover)
    assert "`next`" in value
    assert f"{other}:2" in value
    assert "Next chapter." in value
    assert (_range(hover).start.character, _range(hover).end.character) == (9, 13)


def test_local_label_reference_shows_the_full_name() -> None:
    source = "label chapter:\n    jump .intro\n\nlabel .intro:\n    return\n"

    hover = _hover(source, 1, 10)
    assert hover is not None
    value = _value(hover)
    assert "`chapter.intro`" in value
    assert "(written `.intro`)" in value


def test_declared_image_is_preferred_over_assets() -> None:
    source = 'image bg room = "images/bg.png"\nlabel start:\n    show bg room\n'

    hover = _hover(source, 2, 11)
    assert hover is not None
    value = _value(hover)
    assert "**image** `bg room`" in value
    assert "/script.rpy:1" in value


def test_layeredimage_resolves_from_a_show_statement() -> None:
    source = (
        "layeredimage eileen:\n"
        '    always "eileen_base"\n'
        "\n"
        "label start:\n"
        "    show eileen\n"
    )

    hover = _hover(source, 4, 11)
    assert hover is not None
    assert "**layeredimage** `eileen`" in _value(hover)


def test_automatic_image_asset_is_used_as_a_fallback(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg room.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])

    hover = _hover("label start:\n    show bg room\n", 1, 11, assets=assets)
    assert hover is not None
    value = _value(hover)
    assert "**image** `bg room`" in value
    assert str(image) in value


def test_screen_use_resolves_to_the_screen_declaration() -> None:
    source = 'screen stats():\n    text "Hi"\n\nscreen main_menu():\n    use stats\n'

    hover = _hover(source, 4, 9)
    assert hover is not None
    assert "**screen** `stats`" in _value(hover)


def test_transform_reference_resolves() -> None:
    source = (
        "transform bounce:\n    xoffset 0\n\nlabel start:\n    show eileen at bounce\n"
    )

    hover = _hover(source, 4, 22)
    assert hover is not None
    assert "**transform** `bounce`" in _value(hover)


def test_speaker_resolves_to_the_character_declaration() -> None:
    source = 'define e = Character("Eileen")\n\nlabel start:\n    e "Hi"\n'

    hover = _hover(source, 3, 5)
    assert hover is not None
    value = _value(hover)
    assert "**character** `e`" in value
    assert "/script.rpy:1" in value


def test_builtin_character_hover_has_a_signature_and_docs() -> None:
    source = 'define e = Character("Eileen")\n'

    hover = _hover(source, 0, 12)
    assert hover is not None
    value = _value(hover)
    assert "**function** `Character(" in value
    assert "Creates and returns a Character object" in value
    assert (_range(hover).start.character, _range(hover).end.character) == (11, 20)


def test_builtin_namespaced_function_hover() -> None:
    hover = _hover("label start:\n    renpy.pause(1.0)\n", 1, 9)
    assert hover is not None
    assert "renpy.pause(" in _value(hover)


def test_unknown_name_has_no_hover() -> None:
    assert _hover("label start:\n    jump nowhere\n", 1, 10) is None


def test_builtin_inside_a_string_has_no_hover() -> None:
    source = 'label start:\n    e "renpy.pause"\n'
    assert _hover(source, 1, 10) is None


def test_builtin_inside_a_comment_has_no_hover() -> None:
    assert _hover("# renpy.pause\n", 0, 5) is None


def test_crlf_sources_keep_correct_ranges_and_docs() -> None:
    source = "# Doc.\r\nlabel start:\r\n    return\r\n"

    hover = _hover(source, 1, 7)
    assert hover is not None
    assert "Doc." in _value(hover)
    assert _range(hover).start.line == 1
    assert _range(hover).start.character == 6


def test_emoji_before_a_builtin_uses_utf16_columns() -> None:
    source = "😀 renpy.pause()\n"

    hover = _hover(source, 0, 3)
    assert hover is not None
    assert _range(hover).start.character == utf16_length("😀 ")
    assert _range(hover).end.character == utf16_length("😀 renpy.pause")


def test_continuation_lines_have_no_hover() -> None:
    source = 'label start:\n    e "Hello\n        renpy.pause"\n'
    assert _hover(source, 2, 12) is None


def test_positions_outside_the_document_have_no_hover() -> None:
    source = "label start:\n"
    assert _hover(source, 5, 0) is None
    assert _hover(source, 0, 99) is None


def test_style_parent_reference_resolves() -> None:
    source = 'style base:\n    color "#fff"\n\nstyle dark is base:\n    color "#000"\n'

    hover = _hover(source, 3, 16)
    assert hover is not None
    assert "**style** `base`" in _value(hover)


def test_method_declaration_shows_the_qualified_name() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def hurt(self):\n"
        "            self.hp += 1\n"
    )
    character = source.splitlines()[4].index("hurt") + 1

    hover = _hover(source, 4, character)
    assert hover is not None
    value = _value(hover)
    assert "**method** `Player.hurt`" in value
    assert "Player.hurt(self)" in value


def test_self_field_reference_hover() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def hurt(self):\n"
        "            self.hp += 1\n"
    )
    character = source.splitlines()[5].index("hp") + 1

    hover = _hover(source, 5, character)
    assert hover is not None
    assert "**field** `Player.hp`" in _value(hover)


def test_persistent_reference_hover() -> None:
    source = (
        "define persistent.score = 0\n\nlabel start:\n    $ persistent.score += 1\n"
    )
    character = source.splitlines()[3].index("score") + 1

    hover = _hover(source, 3, character)
    assert hover is not None
    assert "**persistent** `persistent.score`" in _value(hover)


def test_class_base_reference_hover() -> None:
    source = (
        "init python:\n"
        "    class Base:\n"
        "        pass\n"
        "\n"
        "    class Player(Base):\n"
        "        pass\n"
    )
    character = source.splitlines()[4].index("Base") + 1

    hover = _hover(source, 4, character)
    assert hover is not None
    assert "**class** `Base`" in _value(hover)
