"""Tests for rename preparation and workspace edits."""

from pathlib import Path

from lsprotocol import types

from renpy_language_server.assets import AssetIndex
from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.rename import prepare_rename_at, rename_at


def _index(*sources: str) -> WorkspaceIndex:
    workspace = WorkspaceIndex()
    for number, source in enumerate(sources):
        workspace.update(f"file:///script{number}.rpy", source)
    return workspace


def _changes(edit: types.WorkspaceEdit | None) -> dict[str, list[tuple[int, int, str]]]:
    assert edit is not None
    assert edit.changes is not None
    return {
        uri: [
            (item.range.start.line, item.range.start.character, item.new_text)
            for item in edits
        ]
        for uri, edits in edit.changes.items()
    }


def test_prepare_rename_on_a_label_declaration_and_reference() -> None:
    source = "label chapter:\n    jump chapter\n"
    index = _index(source)

    assert prepare_rename_at("file:///script0.rpy", source, 0, 7, index) is not None
    reference = prepare_rename_at("file:///script0.rpy", source, 1, 10, index)
    assert reference is not None
    assert (reference.start.character, reference.end.character) == (9, 16)


def test_prepare_rename_refuses_unknown_text_and_continuations() -> None:
    source = 'label chapter:\n    e "chapter\n        chapter"\n'
    index = _index(source)

    assert prepare_rename_at("file:///script0.rpy", source, 0, 0, index) is None
    assert prepare_rename_at("file:///script0.rpy", source, 1, 10, index) is None
    assert prepare_rename_at("file:///script0.rpy", source, 2, 10, index) is None


def test_global_label_rename_updates_declarations_and_references() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "    jump chapter.intro\n"
        "    jump chapter\n"
        "\n"
        "label .intro:\n"
        "    return\n"
        "\n"
        "label chapter.extra:\n"
        "    return\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "story", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 6, "story"),
            (2, 9, "story.intro"),
            (3, 9, "story"),
            (8, 6, "story.extra"),
        ]
    }


def test_global_label_rename_is_cross_file() -> None:
    index = _index("label start:\n    jump target\n", "label target:\n    return\n")

    edit = rename_at(
        "file:///script0.rpy", "label start:\n    jump target\n", 1, 10, "finish", index
    )
    assert _changes(edit) == {
        "file:///script0.rpy": [(1, 9, "finish")],
        "file:///script1.rpy": [(0, 6, "finish")],
    }


def test_local_label_rename_keeps_the_written_form() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "    jump chapter.intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 4, 7, ".outro", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (1, 9, ".outro"),
            (2, 9, "chapter.outro"),
            (4, 6, ".outro"),
        ]
    }


def test_local_label_rename_accepts_bare_and_full_names() -> None:
    source = "label chapter:\n    jump .intro\n\nlabel .intro:\n    return\n"
    index = _index(source)

    for new_name in ("outro", "chapter.outro"):
        edit = rename_at("file:///script0.rpy", source, 3, 7, new_name, index)
        assert _changes(edit) == {
            "file:///script0.rpy": [(1, 9, ".outro"), (3, 6, ".outro")]
        }


def test_local_label_rename_rejects_a_different_prefix() -> None:
    source = "label chapter:\n    jump .intro\n\nlabel .intro:\n    return\n"
    index = _index(source)

    assert rename_at("file:///script0.rpy", source, 3, 7, "other.outro", index) is None


def test_screen_rename_updates_screen_statements() -> None:
    source = (
        "screen stats():\n"
        '    text "Hi"\n'
        "\n"
        "screen main_menu():\n"
        "    use stats\n"
        "\n"
        "label start:\n"
        "    call screen stats\n"
        "    show screen stats\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "panel", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 7, "panel"),
            (4, 8, "panel"),
            (7, 16, "panel"),
            (8, 16, "panel"),
        ]
    }


def test_transform_rename_updates_at_references() -> None:
    source = (
        "transform bounce:\n"
        "    xoffset 0\n"
        "\n"
        "label start:\n"
        "    show eileen at bounce, bounce\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 10, "hop", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [(0, 10, "hop"), (4, 19, "hop"), (4, 27, "hop")]
    }


def test_image_rename_updates_declarations_and_show_statements() -> None:
    source = (
        'image bg room = "bg.png"\n'
        "\n"
        "label start:\n"
        "    show bg room\n"
        "    scene bg room\n"
        "    hide bg room\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 6, "bg hall", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 6, "bg hall"),
            (3, 9, "bg hall"),
            (4, 10, "bg hall"),
            (5, 9, "bg hall"),
        ]
    }


def test_layeredimage_and_image_share_the_rename_family() -> None:
    source = (
        "layeredimage eileen:\n"
        '    always "base"\n'
        "\n"
        'image eileen = "eileen.png"\n'
        "\n"
        "label start:\n"
        "    show eileen\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 13, "el", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [(0, 13, "el"), (3, 6, "el"), (6, 9, "el")]
    }


def test_character_rename_updates_dialogue_speakers() -> None:
    source = 'define e = Character("Eileen")\n\nlabel start:\n    e "Hello"\n    e happy "Hi"\n'
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "el", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [(0, 7, "el"), (3, 4, "el"), (4, 4, "el")]
    }


def test_rename_refuses_automatic_image_assets(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg room.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])
    source = "label start:\n    show bg room\n"
    index = _index(source)

    # Assets are not declarations, so there is nothing safe to rename.
    assert assets.find_image("bg room") is not None
    assert rename_at("file:///script0.rpy", source, 1, 11, "bg hall", index) is None


def test_invalid_names_are_rejected() -> None:
    source = (
        'image bg = "bg.png"\nscreen stats():\n    pass\nlabel start:\n    jump start\n'
    )
    index = _index(source)

    assert rename_at("file:///script0.rpy", source, 0, 6, "bg-room", index) is None
    assert rename_at("file:///script0.rpy", source, 1, 7, "class", index) is None
    assert rename_at("file:///script0.rpy", source, 3, 7, "a.b", index) is None
    assert rename_at("file:///script0.rpy", source, 4, 10, "", index) is None


def test_renaming_to_the_same_name_is_a_no_op() -> None:
    source = "label start:\n    jump start\n"
    index = _index(source)

    assert rename_at("file:///script0.rpy", source, 0, 7, "start", index) is None


def test_crlf_and_non_ascii_columns_are_preserved() -> None:
    source = 'label start:\r\n    e "😀" \r\n    jump start\r\n'
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "finish", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [(0, 6, "finish"), (2, 9, "finish")]
    }


def test_style_rename_updates_parent_references() -> None:
    source = 'style base:\n    color "#fff"\n\nstyle dark is base:\n    color "#000"\n'
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 6, "root", index)
    assert _changes(edit) == {"file:///script0.rpy": [(0, 6, "root"), (3, 14, "root")]}


def test_variable_rename_updates_define_and_uses() -> None:
    source = (
        'define avtovokzal_ambience = "audio/avtovokzal.mp3"\n'
        "\n"
        "label start:\n"
        "    play music avtovokzal_ambience\n"
        '    $ avtovokzal_ambience = "other.mp3"\n'
        '    if avtovokzal_ambience == "other.mp3":\n'
        "        pass\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 10, "station_ambience", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 7, "station_ambience"),
            (3, 15, "station_ambience"),
            (4, 6, "station_ambience"),
            (5, 7, "station_ambience"),
        ]
    }


def test_variable_rename_from_a_use_is_cross_file() -> None:
    first = 'define ambience = "a.mp3"\nlabel start:\n    play music ambience\n'
    second = "label other:\n    play music ambience\n"
    index = _index(first, second)

    edit = rename_at("file:///script0.rpy", first, 2, 18, "music", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [(0, 7, "music"), (2, 15, "music")],
        "file:///script1.rpy": [(1, 15, "music")],
    }


def test_variable_rename_skips_attributes_keywords_and_strings() -> None:
    source = (
        "define foo = 1\n"
        "label start:\n"
        "    $ obj.foo = foo\n"
        "    $ call(foo=foo)\n"
        "    if (foo == 2):\n"
        '        $ text = "#foo"\n'
        '    e "foo # not a comment"\n'
        "    # foo\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "bar", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 7, "bar"),
            (2, 16, "bar"),
            (3, 15, "bar"),
            (4, 8, "bar"),
        ]
    }


def test_variable_rename_rejects_invalid_names() -> None:
    source = 'define ambience = "a.mp3"\n'
    index = _index(source)

    assert rename_at("file:///script0.rpy", source, 0, 10, "class", index) is None
    assert rename_at("file:///script0.rpy", source, 0, 10, "a.b", index) is None


def test_variable_rename_updates_string_interpolation() -> None:
    source = 'define foo = 1\nlabel start:\n    e "[foo] [foo!t] [obj.foo] [[foo]]"\n'
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "bar", index)
    assert _changes(edit) == {
        "file:///script0.rpy": [
            (0, 7, "bar"),
            (2, 8, "bar"),
            (2, 14, "bar"),
        ]
    }


def test_variable_rename_ignores_renpy_syntax_tokens() -> None:
    source = (
        'define text = "hi"\n'
        'default music = "a.mp3"\n'
        "label start:\n"
        '    play music "a.mp3" loop\n'
        "screen stats():\n"
        "    text text\n"
    )
    index = _index(source)

    music = rename_at("file:///script0.rpy", source, 1, 8, "theme", index)
    assert _changes(music) == {"file:///script0.rpy": [(1, 8, "theme")]}

    text = rename_at("file:///script0.rpy", source, 0, 7, "caption", index)
    assert _changes(text) == {
        "file:///script0.rpy": [(0, 7, "caption"), (5, 9, "caption")]
    }


def test_variable_rename_ignores_dialogue_attributes() -> None:
    source = (
        "define happy = 1\n"
        'define e = Character("Eileen")\n'
        "label start:\n"
        '    e happy "Hi"\n'
        "    show e happy\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 7, "joy", index)
    assert _changes(edit) == {"file:///script0.rpy": [(0, 7, "joy")]}


def test_variable_rename_works_on_continuation_lines() -> None:
    source = "define foo = 1\nlabel start:\n    $ x = (\n        foo\n    )\n"
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 3, 9, "bar", index)
    assert _changes(edit) == {"file:///script0.rpy": [(0, 7, "bar"), (3, 8, "bar")]}


def test_variable_rename_skips_screen_local_defaults() -> None:
    source = (
        "default points = 0\n"
        "screen stats():\n"
        "    default points = 5\n"
        "    text str(points)\n"
        "label start:\n"
        "    $ points += 1\n"
    )
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 8, "score", index)
    assert _changes(edit) == {"file:///script0.rpy": [(0, 8, "score"), (5, 6, "score")]}


def test_variable_rename_handles_priorities_and_operators() -> None:
    source = (
        'define -1 image_dirs = ["images"]\n'
        'define endings += ["extra"]\n'
        "label start:\n"
        '    $ image_dirs.append("dlc")\n'
        '    $ endings.append("more")\n'
    )
    index = _index(source)

    image_dirs = rename_at("file:///script0.rpy", source, 0, 10, "art_dirs", index)
    assert _changes(image_dirs) == {
        "file:///script0.rpy": [(0, 10, "art_dirs"), (3, 6, "art_dirs")]
    }

    endings = rename_at("file:///script0.rpy", source, 1, 7, "routes", index)
    assert _changes(endings) == {
        "file:///script0.rpy": [(1, 7, "routes"), (4, 6, "routes")]
    }


def test_variable_rename_ignores_comments_but_not_later_uses() -> None:
    source = "default item = 1\nlabel start:\n    # see item.\n    $ item += 1\n"
    index = _index(source)

    edit = rename_at("file:///script0.rpy", source, 0, 8, "unit", index)
    assert _changes(edit) == {"file:///script0.rpy": [(0, 8, "unit"), (3, 6, "unit")]}


def test_new_index_families_are_not_renameable_yet() -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def hurt(self):\n"
        "            self.hp -= 1\n"
        "\n"
        "define persistent.score = 0\n"
        "testcase walkthrough:\n"
        "    run start\n"
    )
    index = _index(source)

    # Class, method, field and persistent rename are intentionally deferred.
    assert prepare_rename_at("file:///script0.rpy", source, 1, 11, index) is None
    assert prepare_rename_at("file:///script0.rpy", source, 2, 9, index) is None
    assert prepare_rename_at("file:///script0.rpy", source, 4, 14, index) is None
    assert prepare_rename_at("file:///script0.rpy", source, 7, 20, index) is None
    assert rename_at("file:///script0.rpy", source, 1, 11, "Hero", index) is None
    assert rename_at("file:///script0.rpy", source, 2, 9, "health", index) is None
    assert rename_at("file:///script0.rpy", source, 4, 14, "damage", index) is None
    assert rename_at("file:///script0.rpy", source, 7, 20, "points", index) is None
