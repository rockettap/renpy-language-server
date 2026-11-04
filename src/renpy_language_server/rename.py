"""Rename declarations and their indexed references."""

import keyword
import re

from lsprotocol import types

from .index import Reference, Symbol, WorkspaceIndex, utf16_length
from .resolve import (
    REFERENCE_KINDS,
    Target,
    declarations,
    locate,
    occurrences,
)
from .resolve import target as resolve_target

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*\Z")
_IMAGE_NAME = re.compile(r"[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*\Z")
_RENAME_FAMILIES = frozenset(
    {"label", "screen", "transform", "image", "character", "style", "variable"}
)


def prepare_rename_at(
    uri: str,
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> types.Range | None:
    """Return the written span of the renameable symbol at the cursor."""
    located = locate(uri, source, line, character, index)
    if located is None:
        return None
    resolved = resolve_target(located, index)
    if resolved is None or resolved.family not in _RENAME_FAMILIES:
        return None
    return types.Range(
        start=types.Position(line=line, character=located.start),
        end=types.Position(line=line, character=located.end),
    )


def rename_at(
    uri: str,
    source: str,
    line: int,
    character: int,
    new_name: str,
    index: WorkspaceIndex,
) -> types.WorkspaceEdit | None:
    """Rename the symbol at the cursor and every indexed reference."""
    located = locate(uri, source, line, character, index)
    if located is None:
        return None
    target = resolve_target(located, index)
    if target is None or target.family not in _RENAME_FAMILIES:
        return None

    if target.family == "label":
        edits = _label_edits(target, new_name, index)
    elif target.family == "variable":
        edits = _variable_edits(target, new_name, index)
    else:
        edits = _family_edits(target, new_name, index)

    if not edits:
        return None
    changes = {
        uri: [
            types.TextEdit(
                range=types.Range(
                    start=types.Position(line=line, character=start),
                    end=types.Position(line=line, character=end),
                ),
                new_text=text,
            )
            for (line, start, end), text in sorted(by_uri.items())
        ]
        for uri, by_uri in edits.items()
    }
    return types.WorkspaceEdit(changes=changes)


def document_highlights_at(
    uri: str,
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> list[types.DocumentHighlight] | None:
    """Return every indexed occurrence of the symbol at the cursor."""
    located = locate(uri, source, line, character, index)
    if located is None:
        return None
    target = resolve_target(located, index)
    if target is None:
        return None

    found = occurrences(target, index, uri)
    if not found:
        return None
    return [
        types.DocumentHighlight(
            range=types.Range(
                start=types.Position(line=item.line, character=item.start),
                end=types.Position(line=item.line, character=item.end),
            ),
            kind=(
                types.DocumentHighlightKind.Write
                if item.write
                else types.DocumentHighlightKind.Read
            ),
        )
        for item in found
    ]


def _family_edits(
    target: Target,
    new_name: str,
    index: WorkspaceIndex,
) -> dict[str, dict[tuple[int, int, int], str]]:
    if target.family == "image":
        replacement = _image_name(new_name)
        if replacement is None:
            return {}
    else:
        replacement = _simple_name(new_name)
        if replacement is None:
            return {}

    if replacement == target.name:
        return {}

    edits: dict[str, dict[tuple[int, int, int], str]] = {}
    for symbol in declarations(target.family, target.name, index, target.container):
        _add(edits, symbol.uri, symbol.line, symbol.character, symbol, replacement)

    reference_kinds = REFERENCE_KINDS.get(target.family, frozenset())
    for reference in index.all_references():
        if (
            reference.kind in reference_kinds
            and reference.name == target.name
            and reference.container == target.container
        ):
            _add_reference(edits, reference, replacement)
    return edits


def _variable_edits(
    target: Target,
    new_name: str,
    index: WorkspaceIndex,
) -> dict[str, dict[tuple[int, int, int], str]]:
    replacement = _simple_name(new_name)
    if replacement is None or replacement == target.name:
        return {}

    edits: dict[str, dict[tuple[int, int, int], str]] = {}
    for item in occurrences(target, index):
        _add_span(edits, item.uri, item.line, item.start, item.end, replacement)
    return edits


def _label_edits(
    target: Target,
    new_name: str,
    index: WorkspaceIndex,
) -> dict[str, dict[tuple[int, int, int], str]]:
    if "." in target.name:
        prefix, old_local = target.name.rsplit(".", 1)
        local = _local_name(new_name, prefix)
        if local is None or local == old_local:
            return {}
        replacement = f"{prefix}.{local}"
        local_replacement = f".{local}"
        edits: dict[str, dict[tuple[int, int, int], str]] = {}

        for symbol in index.by_kind("label"):
            if symbol.name != target.name:
                continue
            written = symbol.source_name or symbol.name
            text = local_replacement if written.startswith(".") else replacement
            _add(edits, symbol.uri, symbol.line, symbol.character, symbol, text)

        for reference in index.all_references():
            if reference.kind not in {"jump", "call"}:
                continue
            if reference.name != target.name:
                continue
            text = (
                local_replacement
                if reference.source_name.startswith(".")
                else replacement
            )
            _add_reference(edits, reference, text)
        return edits

    replacement = _simple_name(new_name)
    if replacement is None or replacement == target.name:
        return {}

    edits = {}
    old = target.name
    for symbol in index.by_kind("label"):
        written = symbol.source_name or symbol.name
        if symbol.name == old:
            text = replacement
        elif symbol.name.startswith(f"{old}.") and not written.startswith("."):
            text = replacement + written[len(old) :]
        else:
            continue
        _add(edits, symbol.uri, symbol.line, symbol.character, symbol, text)

    for reference in index.all_references():
        if reference.kind not in {"jump", "call"}:
            continue
        if reference.name != old and not reference.name.startswith(f"{old}."):
            continue
        if reference.source_name.startswith("."):
            continue
        text = replacement + reference.source_name[len(old) :]
        _add_reference(edits, reference, text)
    return edits


def _simple_name(value: str) -> str | None:
    name = value.strip()
    if not _IDENTIFIER.fullmatch(name) or keyword.iskeyword(name):
        return None
    return name


def _local_name(value: str, prefix: str) -> str | None:
    name = value.strip()
    if name.startswith("."):
        name = name[1:]
    elif "." in name:
        expected = f"{prefix}."
        if not name.startswith(expected):
            return None
        name = name[len(expected) :]
    if not _IDENTIFIER.fullmatch(name) or keyword.iskeyword(name):
        return None
    return name


def _image_name(value: str) -> str | None:
    name = " ".join(value.split())
    if not _IMAGE_NAME.fullmatch(name):
        return None
    return name


def _add(
    edits: dict[str, dict[tuple[int, int, int], str]],
    uri: str,
    line: int,
    character: int,
    symbol: Symbol,
    new_text: str,
) -> None:
    written = symbol.source_name or symbol.name
    end = character + utf16_length(written)
    _add_span(edits, uri, line, character, end, new_text)


def _add_reference(
    edits: dict[str, dict[tuple[int, int, int], str]],
    reference: Reference,
    new_text: str,
) -> None:
    _add_span(
        edits,
        reference.uri,
        reference.line,
        reference.character,
        reference.end_character,
        new_text,
    )


def _add_span(
    edits: dict[str, dict[tuple[int, int, int], str]],
    uri: str,
    line: int,
    start: int,
    end: int,
    new_text: str,
) -> None:
    edits.setdefault(uri, {})[(line, start, end)] = new_text
