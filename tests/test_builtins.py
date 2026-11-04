"""Tests for the bundled Ren'Py API table."""

from renpy_language_server.builtins import builtins, iter_builtins, lookup


def test_table_is_populated() -> None:
    assert len(builtins()) >= 1000
    assert all(item.name for item in iter_builtins())


def test_lookup_finds_character_and_pause() -> None:
    character = lookup("Character")
    assert character is not None
    assert character.kind == "function"
    assert character.signature.startswith("Character(")
    assert character.documentation

    pause = lookup("renpy.pause")
    assert pause is not None
    assert pause.category == "renpy"
    assert pause.signature.startswith("renpy.pause(")


def test_lookup_is_case_sensitive_and_returns_none_for_unknown() -> None:
    assert lookup("character") is None
    assert lookup("definitely_not_a_renpy_name") is None


def test_table_is_cached() -> None:
    assert builtins() is builtins()
