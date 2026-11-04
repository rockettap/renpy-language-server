"""Signature help for built-ins and user declarations."""

import re
from typing import cast

from lsprotocol import types

from . import builtins as api
from .index import (
    Symbol,
    SymbolKind,
    WorkspaceIndex,
    enclosing_python_class,
)

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z")
_MAX_SCAN = 200_000


def signature_at(
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> types.SignatureHelp | None:
    """Return signature help for the call containing the cursor, if any."""
    offset = _offset(source, line, character)
    if offset is None:
        return None

    open_index = _unmatched_paren(source, offset)
    if open_index is None:
        return None
    callee = _callee(source, open_index)
    if callee is None:
        return None

    name, name_start = callee
    builtin = api.lookup(name)
    if builtin is not None:
        label = builtin.signature
        parameters = _parameter_labels(builtin.args)
        documentation: str | None = builtin.documentation or None
    else:
        symbol = _user_symbol(source, name, name_start, index)
        if symbol is None:
            return None
        label, parameters = _symbol_signature(symbol, index)
        documentation = f"{symbol.kind} `{symbol.name}`"

    active = _active_parameter(source, open_index + 1, offset)
    if parameters:
        active = min(active, len(parameters) - 1)
    else:
        active = None

    signature = types.SignatureInformation(
        label=label,
        documentation=documentation,
        parameters=[
            types.ParameterInformation(label=parameter) for parameter in parameters
        ],
    )
    return types.SignatureHelp(
        signatures=[signature],
        active_signature=0,
        active_parameter=active,
    )


def _offset(source: str, line: int, character: int) -> int | None:
    """Convert a server line/character pair to an absolute offset."""
    lines = source.splitlines(keepends=True)
    if line < 0 or line >= len(lines):
        return None
    content = lines[line].rstrip("\r\n")
    if character < 0 or character > len(content):
        return None
    return sum(len(item) for item in lines[:line]) + character


def _unmatched_paren(source: str, end: int) -> int | None:
    """Return the innermost unmatched ``(`` before ``end``."""
    start = max(0, end - _MAX_SCAN)
    stack: list[int] = []
    index = start
    quote: str | None = None
    triple = False
    escaped = False

    while index < end:
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if triple and source.startswith(quote * 3, index):
                index += 3
                quote = None
                triple = False
                continue
            if not triple and char == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            newline = source.find("\n", index)
            if newline < 0 or newline >= end:
                break
            index = newline + 1
            continue
        if char in "\"'":
            triple = source.startswith(char * 3, index)
            quote = char
            index += 3 if triple else 1
            continue
        if char in "([{":
            stack.append(index)
        elif char in ")]}" and stack:
            stack.pop()
        index += 1

    for position in reversed(stack):
        if source[position] == "(":
            return position
    return None


def _callee(source: str, open_index: int) -> tuple[str, int] | None:
    """Return the dotted name immediately before ``open_index``."""
    index = open_index - 1
    while index >= 0 and source[index] in " \t":
        index -= 1
    end = index + 1
    while index >= 0 and (source[index].isalnum() or source[index] in "_."):
        index -= 1
    start = index + 1
    name = source[start:end]
    if not _IDENTIFIER.fullmatch(name):
        return None
    return name, start


def _user_symbol(
    source: str,
    name: str,
    name_start: int,
    index: WorkspaceIndex,
) -> Symbol | None:
    hint = _family_hint(_line_prefix(source, name_start))
    if hint is not None:
        found = index.find(cast(SymbolKind, hint), name)
        return found[0] if found else None

    if "." in name:
        return _member_symbol(source, name, name_start, index)

    for family in ("class", "callable", "label", "screen", "transform"):
        found = index.find(cast(SymbolKind, family), name)
        if found:
            return found[0]
    return None


def _member_symbol(
    source: str,
    name: str,
    name_start: int,
    index: WorkspaceIndex,
) -> Symbol | None:
    """Resolve ``Class.method`` and ``self.method`` calls without guessing."""
    owner, _, member = name.rpartition(".")
    if owner in {"self", "cls"}:
        line = source.count("\n", 0, name_start)
        container = enclosing_python_class(source, line)
    elif index.find("class", owner):
        container = owner
    else:
        container = None
    if not container:
        return None
    for kind in ("method", "callable", "field", "property"):
        found = [
            symbol
            for symbol in index.find(cast(SymbolKind, kind), member)
            if symbol.container == container
        ]
        if found:
            return found[0]
    return None


def _symbol_signature(symbol: Symbol, index: WorkspaceIndex) -> tuple[str, list[str]]:
    """Render a user declaration, unwrapping class constructors and ``self``."""
    source = symbol
    if symbol.kind == "class" and not symbol.parameters:
        constructors = [
            candidate
            for candidate in index.find("method", "__init__")
            if candidate.container == symbol.name
        ]
        if constructors:
            source = constructors[0]

    parameters_text = source.parameters.strip()
    if source.kind in {"method", "property"}:
        parameters_text = _without_self(parameters_text)
    parameters = _parameter_labels(parameters_text)
    label = (
        f"{symbol.name}({parameters_text})" if parameters_text else f"{symbol.name}()"
    )
    return label, parameters


def _without_self(text: str) -> str:
    """Remove a leading ``self`` or ``cls`` while keeping defaults intact."""
    value = text.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    parts = _split_top_level(value)
    if parts:
        first = parts[0].strip()
        name = first.split("=", 1)[0].split(":", 1)[0].strip().lstrip("*")
        if name in {"self", "cls"}:
            parts = parts[1:]
    return ", ".join(part.strip() for part in parts if part.strip())


def _line_prefix(source: str, position: int) -> str:
    start = source.rfind("\n", 0, position) + 1
    return source[start:position].split("#", 1)[0]


def _family_hint(prefix: str) -> str | None:
    words = prefix.split()
    if len(words) >= 2 and words[-2:] in (
        ["call", "screen"],
        ["show", "screen"],
        ["hide", "screen"],
    ):
        return "screen"
    if words and words[0] == "use":
        return "screen"
    if words and words[-1] == "call":
        return "label"
    return None


def _parameter_labels(text: str) -> list[str]:
    """Split a parameter list into labels suitable for signature help."""
    value = text.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    result: list[str] = []
    for part in _split_top_level(value):
        item = part.strip()
        if not item or item in {"*", "/"}:
            continue
        name = item.split("=", 1)[0].split(":", 1)[0].strip()
        if name and name not in {"*", "/"}:
            result.append(name)
    return result


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    quote: str | None = None
    triple = False
    escaped = False

    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if triple and text.startswith(quote * 3, index):
                index += 3
                quote = None
                triple = False
                continue
            if not triple and char == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                break
            index = newline + 1
            continue
        if char in "\"'":
            triple = text.startswith(char * 3, index)
            quote = char
            index += 3 if triple else 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1

    parts.append(text[start:])
    return parts


def _active_parameter(source: str, start: int, end: int) -> int:
    """Count top-level commas between the open paren and the cursor."""
    active = 0
    depth = 0
    index = start
    quote: str | None = None
    triple = False
    escaped = False

    while index < end:
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if triple and source.startswith(quote * 3, index):
                index += 3
                quote = None
                triple = False
                continue
            if not triple and char == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            newline = source.find("\n", index)
            if newline < 0 or newline >= end:
                break
            index = newline + 1
            continue
        if char in "\"'":
            triple = source.startswith(char * 3, index)
            quote = char
            index += 3 if triple else 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            active += 1
        index += 1

    return active
