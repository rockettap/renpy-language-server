"""Tests for the per-file and workspace symbol index."""

from pathlib import Path

from renpy_language_server.index import (
    WorkspaceIndex,
    global_label_at,
    parse_document,
    resolve_label_name,
    scan_workspace,
    utf16_length,
)


def test_parse_document_finds_every_symbol_kind() -> None:
    source = """\
label start:
    return

screen main_menu():
    text "Hello"

transform bounce:
    ease 0.2 yoffset -10

image bg room = "bg room.png"

define e = Character("Eileen", color="#fff")
"""
    index = parse_document("file:///script.rpy", source)

    found = [(item.kind, item.name, item.line, item.end_line) for item in index.symbols]
    assert found == [
        ("label", "start", 0, 1),
        ("screen", "main_menu", 3, 4),
        ("transform", "bounce", 6, 7),
        ("image", "bg room", 9, 9),
        ("character", "e", 11, 11),
    ]


def test_character_detail_contains_the_display_name() -> None:
    source = 'define e = Character("Eileen")\n'
    index = parse_document("file:///script.rpy", source)

    assert index.symbols[0].detail == 'character "Eileen"'


def test_duplicate_labels_are_kept() -> None:
    source = "label start:\n    return\n"
    workspace = WorkspaceIndex()
    workspace.update("file:///a.rpy", source)
    workspace.update("file:///b.rpy", source)

    assert len(workspace.find("label", "start")) == 2
    assert set(workspace.labels()) == {"start"}


def test_update_replaces_only_the_given_file() -> None:
    workspace = WorkspaceIndex()
    workspace.update("file:///a.rpy", "label a:\n    return\n")
    workspace.update("file:///b.rpy", "label b:\n    return\n")
    workspace.update("file:///a.rpy", "label a2:\n    return\n")

    assert workspace.find("label", "a") == []
    assert len(workspace.find("label", "a2")) == 1
    assert len(workspace.find("label", "b")) == 1


def test_remove_drops_the_file() -> None:
    workspace = WorkspaceIndex()
    workspace.update("file:///a.rpy", "label a:\n    return\n")
    workspace.remove("file:///a.rpy")

    assert workspace.all_symbols() == []


def test_scan_workspace_includes_rpym_and_skips_cache(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    (game / "extra.rpym").write_text("label extra:\n    return\n", encoding="utf-8")
    cache = game / "cache"
    cache.mkdir()
    (cache / "ignored.rpy").write_text("label ignored:\n    return\n", encoding="utf-8")

    documents = scan_workspace([tmp_path])
    names = sorted(symbol.name for doc in documents for symbol in doc.symbols)

    assert names == ["extra", "start"]


def test_scan_workspace_ignores_unreadable_and_wrong_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("label nope:\n", encoding="utf-8")
    documents = scan_workspace([tmp_path])
    assert documents == []


def test_non_ascii_text_before_a_symbol_uses_utf16_units() -> None:
    # The comment is irrelevant to the symbol, but the line is still measured
    # through the UTF-16 helper below.
    assert utf16_length("😀") == 2
    assert utf16_length("Привіт") == 6


def test_malformed_source_does_not_raise() -> None:
    index = parse_document("file:///bad.rpy", 'label start:\n    e "\n')
    assert index.symbols[0].name == "start"


def test_local_labels_are_stored_under_their_full_name() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
        "\n"
        "label other:\n"
        "    jump .intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
    )
    document = parse_document("file:///script.rpy", source)
    labels = [item for item in document.symbols if item.kind == "label"]

    assert [item.name for item in labels] == [
        "chapter",
        "chapter.intro",
        "other",
        "other.intro",
    ]
    # Selection ranges still point at the written ``.intro`` text.
    assert [item.source_name for item in labels] == [
        "chapter",
        ".intro",
        "other",
        ".intro",
    ]


def test_full_name_local_label_updates_the_global_context() -> None:
    source = "label chapter.intro:\n    return\n\nlabel .next:\n    return\n"
    document = parse_document("file:///script.rpy", source)

    assert [item.name for item in document.symbols] == [
        "chapter.intro",
        "chapter.next",
    ]


def test_global_label_at_and_resolve_label_name() -> None:
    source = "label chapter:\n    jump .intro\n\nlabel other:\n    jump .intro\n"

    assert global_label_at(source, 1) == "chapter"
    assert global_label_at(source, 4) == "other"
    assert resolve_label_name(source, 1, ".intro") == "chapter.intro"
    assert resolve_label_name(source, 4, ".intro") == "other.intro"
    assert resolve_label_name(source, 1, "plain") == "plain"
    assert resolve_label_name("jump .orphan\n", 0, ".orphan") is None


def test_style_and_layeredimage_are_indexed() -> None:
    source = (
        "style dark_button is button:\n"
        '    background "#222"\n'
        "\n"
        "layeredimage eileen:\n"
        '    always "eileen_base"\n'
    )
    document = parse_document("file:///script.rpy", source)

    assert [(item.kind, item.name) for item in document.symbols] == [
        ("style", "dark_button"),
        ("layeredimage", "eileen"),
    ]


def test_declaration_parameters_are_captured() -> None:
    source = (
        "label start(name, count=2):\n"
        "    return\n"
        "\n"
        'screen stats(value, title="Stats"):\n'
        "    text title\n"
        "\n"
        "transform slide(x=0.0):\n"
        "    xoffset x\n"
    )
    document = parse_document("file:///script.rpy", source)

    assert [(item.name, item.parameters) for item in document.symbols] == [
        ("start", "name, count=2"),
        ("stats", 'value, title="Stats"'),
        ("slide", "x=0.0"),
    ]


def test_declaration_without_parameters_is_empty() -> None:
    document = parse_document("file:///script.rpy", "label start:\n    return\n")
    assert document.symbols[0].parameters == ""


def test_parentheses_in_strings_do_not_break_parameters() -> None:
    source = 'label start(text="a)b"):\n    return\n'
    document = parse_document("file:///script.rpy", source)

    assert document.symbols[0].parameters == 'text="a)b"'


def test_define_and_default_variables_are_indexed() -> None:
    source = (
        'define ambience = "audio/theme.mp3"\n'
        "default points = 0\n"
        'define e = Character("Eileen")\n'
    )
    document = parse_document("file:///script.rpy", source)

    assert [(item.kind, item.name, item.detail) for item in document.symbols] == [
        ("variable", "ambience", "define"),
        ("variable", "points", "default"),
        ("character", "e", 'character "Eileen"'),
    ]


def test_screen_local_defaults_are_not_global_symbols() -> None:
    source = "screen stats():\n    default points = 5\n    text str(points)\n"
    document = parse_document("file:///script.rpy", source)

    assert [(item.kind, item.name) for item in document.symbols] == [
        ("screen", "stats")
    ]


def test_define_priorities_and_operators_are_indexed() -> None:
    source = (
        'define -1 image_dirs = ["images"]\n'
        'define endings += ["extra"]\n'
        'default flags |= {"x"}\n'
        'define -2 e = Character("Eileen")\n'
    )
    document = parse_document("file:///script.rpy", source)

    assert [(item.kind, item.name) for item in document.symbols] == [
        ("variable", "image_dirs"),
        ("variable", "endings"),
        ("variable", "flags"),
        ("character", "e"),
    ]
