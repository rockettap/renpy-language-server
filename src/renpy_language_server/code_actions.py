"""Quick fixes for diagnostics that can be repaired without guessing."""

import re
from collections.abc import Sequence

from lsprotocol import types

from .diagnostics import COMPARISON, STRAY_DOLLAR, TABS, UNKNOWN_LABEL
from .index import utf16_length

_UNKNOWN_LABEL = re.compile(r"Unknown label '(.+)'\.")


def code_actions_for(
    uri: str,
    source: str,
    requested: types.Range,
    diagnostics: Sequence[types.Diagnostic],
    indent: int = 4,
) -> list[types.CodeAction]:
    """Return quick fixes for diagnostics overlapping ``requested``."""
    actions: list[types.CodeAction] = []
    for diagnostic in diagnostics:
        if not _overlaps(diagnostic.range, requested):
            continue
        action = _action(uri, source, diagnostic, indent)
        if action is not None:
            actions.append(action)
    return actions


def _action(
    uri: str,
    source: str,
    diagnostic: types.Diagnostic,
    indent: int,
) -> types.CodeAction | None:
    code = diagnostic.code
    if code == COMPARISON:
        return _edit_action(
            uri,
            'Replace "=" with "=="',
            diagnostic,
            diagnostic.range,
            "==",
        )
    if code == STRAY_DOLLAR:
        return _edit_action(
            uri,
            'Remove stray "$"',
            diagnostic,
            diagnostic.range,
            "",
        )
    if code == TABS:
        tabs = _text_at(source, diagnostic.range)
        if "\t" not in tabs:
            return None
        return _edit_action(
            uri,
            "Replace tabs with spaces",
            diagnostic,
            diagnostic.range,
            " " * (indent * tabs.count("\t")),
        )
    if code == UNKNOWN_LABEL:
        match = _UNKNOWN_LABEL.fullmatch(diagnostic.message)
        if match is None:
            return None
        name = match.group(1)
        if not name or name.startswith("."):
            return None
        return _edit_action(
            uri,
            f"Create label '{name}'",
            diagnostic,
            _end_of_document(source),
            _new_label(source, name, indent),
        )
    return None


def _edit_action(
    uri: str,
    title: str,
    diagnostic: types.Diagnostic,
    range_: types.Range,
    new_text: str,
) -> types.CodeAction:
    return types.CodeAction(
        title=title,
        kind=types.CodeActionKind.QuickFix,
        diagnostics=[diagnostic],
        edit=types.WorkspaceEdit(
            changes={uri: [types.TextEdit(range=range_, new_text=new_text)]}
        ),
    )


def _new_label(source: str, name: str, indent: int) -> str:
    separator = "" if not source or source.endswith("\n") else "\n"
    return f"{separator}\nlabel {name}:\n{' ' * indent}return\n"


def _end_of_document(source: str) -> types.Range:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    return types.Range(
        start=types.Position(line=len(lines) - 1, character=utf16_length(lines[-1])),
        end=types.Position(line=len(lines) - 1, character=utf16_length(lines[-1])),
    )


def _text_at(source: str, range_: types.Range) -> str:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if range_.start.line != range_.end.line:
        return ""
    if range_.start.line >= len(lines):
        return ""
    return lines[range_.start.line][range_.start.character : range_.end.character]


def _overlaps(left: types.Range, right: types.Range) -> bool:
    return _position(left.start) <= _position(right.end) and _position(
        right.start
    ) <= _position(left.end)


def _position(position: types.Position) -> tuple[int, int]:
    return position.line, position.character
