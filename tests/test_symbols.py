"""Tests for LSP document symbols."""

from lsprotocol import types

from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.symbols import document_symbols, workspace_symbols

SOURCE = """\
label start:
    return

screen main_menu():
    text "Hello"

transform bounce:
    ease 0.2 yoffset -10

image bg room = "bg room.png"

define e = Character("Eileen")
"""


def test_symbol_names_kinds_and_ranges() -> None:
    symbols = document_symbols("file:///script.rpy", SOURCE)

    assert [(item.name, item.kind) for item in symbols] == [
        ("start", types.SymbolKind.Function),
        ("main_menu", types.SymbolKind.Class),
        ("bounce", types.SymbolKind.Constructor),
        ("bg room", types.SymbolKind.Field),
        ("e", types.SymbolKind.Variable),
    ]

    label = symbols[0]
    assert label.range.start == types.Position(line=0, character=0)
    assert label.range.end == types.Position(line=1, character=len("    return"))
    assert label.selection_range.start == types.Position(line=0, character=6)
    assert label.selection_range.end == types.Position(line=0, character=11)


def test_empty_and_comment_only_files_have_no_symbols() -> None:
    assert document_symbols("file:///empty.rpy", "") == []
    assert document_symbols("file:///comments.rpy", "# label nope:\n") == []


def test_malformed_source_is_safe() -> None:
    symbols = document_symbols("file:///bad.rpy", 'label start:\n    e "\n')
    assert symbols[0].name == "start"


def test_local_label_selection_range_uses_the_written_name() -> None:
    source = "label chapter:\n    return\n\nlabel .intro:\n    return\n"
    symbols = document_symbols("file:///script.rpy", source)

    assert [item.name for item in symbols] == ["chapter", "chapter.intro"]
    local = symbols[1]
    assert local.selection_range.start == types.Position(line=3, character=6)
    assert local.selection_range.end == types.Position(line=3, character=12)


def test_style_and_layeredimage_symbol_kinds() -> None:
    source = (
        'style dark:\n    color "#000"\n\nlayeredimage eileen:\n    always "base"\n'
    )
    symbols = document_symbols("file:///script.rpy", source)

    assert [(item.name, item.kind) for item in symbols] == [
        ("dark", types.SymbolKind.Interface),
        ("eileen", types.SymbolKind.Field),
    ]


def test_python_members_are_nested_under_their_class() -> None:
    source = """\
init python:
    class Player:
        hp = 10

        def hurt(self):
            self.hp -= 1

define persistent.score = 0
testcase walkthrough:
    run start
translate spanish strings:
    old "Hello"
    new "Hola"
"""
    symbols = document_symbols("file:///script.rpy", source)

    assert [(item.name, item.kind) for item in symbols] == [
        ("Player", types.SymbolKind.Class),
        ("score", types.SymbolKind.Variable),
        ("walkthrough", types.SymbolKind.Function),
        ("strings", types.SymbolKind.String),
    ]
    player = symbols[0]
    assert [(item.name, item.kind) for item in player.children or []] == [
        ("hp", types.SymbolKind.Field),
        ("hurt", types.SymbolKind.Method),
    ]


def test_nested_classes_are_nested_in_the_outline() -> None:
    source = """\
init python:
    class Outer:
        class Inner:
            value = 1
"""
    symbols = document_symbols("file:///script.rpy", source)

    assert [item.name for item in symbols] == ["Outer"]
    outer = symbols[0]
    assert [item.name for item in outer.children or []] == ["Inner"]
    inner = (outer.children or [])[0]
    assert [item.name for item in inner.children or []] == ["value"]


def test_store_members_are_nested_under_the_store() -> None:
    source = """\
init python in mystore:
    gold = 5

    def buy(item):
        return item
"""
    symbols = document_symbols("file:///script.rpy", source)

    assert [(item.name, item.kind) for item in symbols] == [
        ("mystore", types.SymbolKind.Namespace)
    ]
    assert [(item.name, item.kind) for item in symbols[0].children or []] == [
        ("gold", types.SymbolKind.Field),
        ("buy", types.SymbolKind.Function),
    ]


def test_workspace_symbols_rank_exact_then_prefix_then_substring() -> None:
    index = WorkspaceIndex()
    index.update(
        "file:///a.rpy",
        "label start:\n    return\n\nlabel restart:\n    return\n\n"
        "label chapter_start:\n    return\n",
    )
    index.update("file:///b.rpy", "screen start_screen():\n    pass\n")

    assert [item.name for item in workspace_symbols(index, "start")] == [
        "start",
        "start_screen",
        "chapter_start",
        "restart",
    ]


def test_workspace_symbols_report_kind_location_and_container() -> None:
    source = (
        "init python:\n    class Hero:\n        def attack(self):\n            pass\n"
    )
    index = WorkspaceIndex()
    index.update("file:///script.rpy", source)

    symbols = workspace_symbols(index, "att")
    assert len(symbols) == 1
    symbol = symbols[0]
    assert symbol.name == "attack"
    assert symbol.kind == types.SymbolKind.Method
    assert symbol.container_name == "Hero"
    assert symbol.location.uri == "file:///script.rpy"
    assert symbol.location.range.start == types.Position(line=2, character=12)


def test_workspace_symbols_cap_an_empty_query() -> None:
    index = WorkspaceIndex()
    index.update(
        "file:///script.rpy",
        "".join(f"label chapter_{number}:\n    return\n\n" for number in range(20)),
    )

    assert len(workspace_symbols(index, "", limit=5)) == 5


def test_workspace_symbols_use_utf16_columns() -> None:
    source = "label café:\n    return\n"
    index = WorkspaceIndex()
    index.update("file:///script.rpy", source)

    symbol = workspace_symbols(index, "café")[0]
    assert symbol.location.range.end.character == 10


def test_workspace_symbol_search_is_fast_on_a_large_index() -> None:
    import time

    index = WorkspaceIndex()
    index.update(
        "file:///large.rpy",
        "".join(f"label chapter_{number}:\n    return\n\n" for number in range(5000)),
    )

    started = time.perf_counter()
    symbols = workspace_symbols(index, "chapter_4999")
    elapsed = time.perf_counter() - started

    assert [symbol.name for symbol in symbols] == ["chapter_4999"]
    assert elapsed < 1.0
