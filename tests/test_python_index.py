"""Tests for declarations inside Ren'Py Python blocks and related declaration families."""

import pytest

from renpy_language_server import python_index
from renpy_language_server.analysis import analyze
from renpy_language_server.index import (
    IndexOptions,
    enclosing_python_class,
    parse_document,
)
from renpy_language_server.python_index import parse_python


def _symbols(source: str, options: IndexOptions | None = None):
    document = parse_document("file:///script.rpy", source, options=options)
    return [
        (item.kind, item.container, item.name, item.line, item.parameters)
        for item in document.symbols
    ]


def test_python_classes_methods_properties_and_fields() -> None:
    source = """\
init python:
    class Base:
        pass

    class Player(Base):
        hp = 10

        @property
        def alive(self):
            return self.hp > 0

        def hurt(self, amount=1):
            self.hp -= amount
            return self.hp

    def helper(value):
        return value
"""
    assert _symbols(source) == [
        ("class", "", "Base", 1, ""),
        ("class", "", "Player", 4, ""),
        ("field", "Player", "hp", 5, ""),
        ("property", "Player", "alive", 8, "self"),
        ("method", "Player", "hurt", 11, "self, amount=1"),
        ("callable", "", "helper", 15, "value"),
    ]


def test_nested_classes_keep_their_outer_container() -> None:
    source = """\
init python:
    class Outer:
        class Inner:
            value = 1
"""
    assert _symbols(source) == [
        ("class", "", "Outer", 1, ""),
        ("class", "Outer", "Inner", 2, ""),
        ("field", "Inner", "value", 3, ""),
    ]


def test_multi_line_function_signature_is_joined() -> None:
    source = """\
init python:
    def long_name(
        first,
        second=2,
    ):
        return first
"""
    symbols = _symbols(source)
    assert [(kind, name) for kind, _, name, _, _ in symbols] == [
        ("callable", "long_name")
    ]
    assert "first" in symbols[0][4]
    assert "second=2" in symbols[0][4]


def test_store_blocks_are_indexed_with_their_members() -> None:
    source = """\
init python in mystore:
    gold = 5

    def buy(item):
        return item

python early in earlystore:
    flag = True
"""
    assert _symbols(source) == [
        ("store", "", "mystore", 0, ""),
        ("field", "mystore", "gold", 1, ""),
        ("callable", "mystore", "buy", 3, "item"),
        ("store", "", "earlystore", 6, ""),
        ("field", "earlystore", "flag", 7, ""),
    ]


def test_prioritized_python_blocks_are_indexed() -> None:
    source = """\
init -1 python:
    class Early:
        pass

init 10 python in later:
    value = 1
"""
    assert _symbols(source) == [
        ("class", "", "Early", 1, ""),
        ("store", "", "later", 4, ""),
        ("field", "later", "value", 5, ""),
    ]


def test_persistent_testcase_and_translation_families() -> None:
    source = """\
define persistent.player_name = "Alex"
default persistent.score = 0
define -1 persistent.flags += ["x"]

testcase walkthrough:
    run start

translate spanish strings:
    old "Hello"
    new "Hola"

translate None strings:
    old "x"
    new "x"
"""
    assert _symbols(source) == [
        ("persistent", "persistent", "player_name", 0, ""),
        ("persistent", "persistent", "score", 1, ""),
        ("persistent", "persistent", "flags", 2, ""),
        ("testcase", "", "walkthrough", 4, ""),
        ("translation", "spanish", "strings", 7, ""),
        ("translation", "None", "strings", 11, ""),
    ]


def test_persistent_is_not_also_a_plain_variable() -> None:
    document = parse_document("file:///script.rpy", "define persistent.score = 0\n")
    assert [(item.kind, item.name) for item in document.symbols] == [
        ("persistent", "score")
    ]


def test_member_references_are_indexed_conservatively() -> None:
    source = """\
init python:
    class Player:
        hp = 10

        def hurt(self):
            self.hp -= 1
            return self.hp

    class Enemy:
        hp = 5

label start:
    $ Player.hp = 2
    $ p.hp = 3
    $ a.b.c = 4
    $ "Player.hp"
    # Player.hp
    $ persistent.score += 1
    $ store.gold += 1
"""
    document = parse_document("file:///script.rpy", source)
    found = [
        (item.kind, item.container, item.name, item.line)
        for item in document.references
        if item.kind in {"member", "persistent", "store", "class"}
    ]
    assert found == [
        ("member", "Player", "hp", 5),
        ("member", "Player", "hp", 6),
        ("member", "Player", "hp", 12),
        ("persistent", "persistent", "score", 17),
        ("store", "store", "gold", 18),
    ]


def test_class_bases_are_referenced() -> None:
    source = """\
init python:
    class Base:
        pass

    class Player(Base, mixin.Helper):
        pass
"""
    document = parse_document("file:///script.rpy", source)
    assert [
        (item.kind, item.name, item.line)
        for item in document.references
        if item.kind == "class"
    ] == [("class", "Base", 4), ("class", "Helper", 4)]


def test_extended_index_can_be_disabled() -> None:
    source = """\
init python:
    class Player:
        hp = 10

define persistent.score = 0
testcase walkthrough:
    run start
label start:
    $ Player.hp = 1
"""
    document = parse_document(
        "file:///script.rpy", source, options=IndexOptions(extended=False)
    )
    assert [(item.kind, item.name) for item in document.symbols] == [("label", "start")]
    assert document.references == ()


def test_member_references_can_be_disabled() -> None:
    source = """\
init python:
    class Player:
        hp = 10
label start:
    $ Player.hp = 1
    $ persistent.score = 2
    $ store.gold = 3
define persistent.score = 0
"""
    document = parse_document(
        "file:///script.rpy", source, options=IndexOptions(members=False)
    )
    assert [
        item.kind
        for item in document.references
        if item.kind in {"member", "persistent", "store"}
    ] == []


def test_enclosing_python_class() -> None:
    source = """\
init python:
    class Player:
        def hurt(self):
            self.hp = 1

    def helper():
        pass
"""
    assert enclosing_python_class(source, 2) == "Player"
    assert enclosing_python_class(source, 5) is None
    assert enclosing_python_class("label start:\n    pass\n", 0) is None


def test_malformed_python_never_raises() -> None:
    source = """\
init python:
    class :
        pass
    def (:
    self.
    class Broken(
"""
    document = parse_document("file:///bad.rpy", source)
    assert isinstance(document.symbols, tuple)


def test_symbol_cap_stops_pathological_files() -> None:
    source = "init python:\n" + "".join(
        f"    class C{number}:\n        pass\n" for number in range(5)
    )
    analysis = analyze(source)
    raw_lines = source.split("\n")
    parsed = parse_python(analysis, raw_lines, len(source), max_symbols=2)
    assert parsed.truncated is True
    assert len(parsed.symbols) == 2


def test_large_files_skip_python_body_indexing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(python_index, "MAX_PYTHON_BYTES", 10)
    source = """\
init python:
    class Player:
        pass

label start:
    return
"""
    document = parse_document("file:///script.rpy", source)
    assert [(item.kind, item.name) for item in document.symbols] == [("label", "start")]
