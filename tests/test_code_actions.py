"""Tests for diagnostic quick fixes."""

from typing import cast

from lsprotocol import types

from renpy_language_server.code_actions import code_actions_for
from renpy_language_server.diagnostics import diagnostics_for_document
from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.settings import (
    DEFAULT_DIAGNOSTIC_RULES,
    DiagnosticSeveritySetting,
    Settings,
)

URI = "file:///script.rpy"
FULL_RANGE = types.Range(
    start=types.Position(line=0, character=0),
    end=types.Position(line=1000, character=0),
)


def _diagnostics(source: str, **rules: str) -> list[types.Diagnostic]:
    merged = cast(
        dict[str, DiagnosticSeveritySetting],
        {**DEFAULT_DIAGNOSTIC_RULES, **rules},
    )
    settings = Settings(diagnostic_rules=merged)
    index = WorkspaceIndex()
    index.update(URI, source)
    return diagnostics_for_document(source, index, settings, URI)


def _actions(
    source: str, requested: types.Range = FULL_RANGE, **rules: str
) -> list[types.CodeAction]:
    return code_actions_for(
        URI,
        source,
        requested,
        _diagnostics(source, **rules),
    )


def _edit(action: types.CodeAction) -> types.TextEdit:
    assert action.edit is not None
    assert action.edit.changes is not None
    return cast(list[types.TextEdit], action.edit.changes[URI])[0]


def test_comparison_quick_fix_replaces_the_operator() -> None:
    source = "label start:\n    $ if a = 1:\n        pass\n"
    actions = _actions(source, comparison="warning")

    assert [action.title for action in actions] == ['Replace "=" with "=="']
    edit = _edit(actions[0])
    assert edit.range == types.Range(
        start=types.Position(line=1, character=11),
        end=types.Position(line=1, character=12),
    )
    assert edit.new_text == "=="


def test_stray_dollar_quick_fix_removes_the_marker() -> None:
    source = "label start:\n    $ a = 1 $ b = 2\n"
    actions = _actions(source, stray_dollar="warning")

    assert [action.title for action in actions] == ['Remove stray "$"']
    edit = _edit(actions[0])
    assert edit.new_text == ""
    assert edit.range.start == types.Position(line=1, character=12)


def test_tabs_quick_fix_uses_the_configured_indent() -> None:
    source = "label start:\n\t\treturn\n"
    actions = code_actions_for(
        URI,
        source,
        FULL_RANGE,
        _diagnostics(source),
        indent=2,
    )

    assert [action.title for action in actions] == ["Replace tabs with spaces"]
    edit = _edit(actions[0])
    assert edit.new_text == "    "


def test_unknown_label_quick_fix_appends_a_label() -> None:
    source = "label start:\n    jump missing\n"
    actions = _actions(source)

    assert [action.title for action in actions] == ["Create label 'missing'"]
    edit = _edit(actions[0])
    assert edit.new_text == "\nlabel missing:\n    return\n"
    assert source + edit.new_text == (
        "label start:\n    jump missing\n\nlabel missing:\n    return\n"
    )


def test_actions_require_an_overlapping_diagnostic() -> None:
    source = "label start:\n    jump missing\n"
    requested = types.Range(
        start=types.Position(line=0, character=0),
        end=types.Position(line=0, character=5),
    )

    assert _actions(source, requested) == []


def test_non_fixable_diagnostics_do_not_produce_actions() -> None:
    diagnostic = types.Diagnostic(
        range=types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=1),
        ),
        message="Unknown image 'nope'.",
        code="renpy-language-server.unknown-image",
    )

    assert code_actions_for(URI, "", FULL_RANGE, [diagnostic]) == []
