"""Hover content for declarations, references, assets and built-ins."""

import re
from pathlib import Path

from lsprotocol import types
from pygls.uris import to_fs_path

from . import builtins as api
from .analysis import analyze
from .assets import Asset, AssetIndex
from .docs import comment_block
from .index import (
    Reference,
    Symbol,
    WorkspaceIndex,
    display_name,
    utf16_length,
)
from .resolve import declarations

_WORD = re.compile(r"[A-Za-z_][\w.]*")


def hover_at(
    uri: str,
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
    assets: AssetIndex,
) -> types.Hover | None:
    """Return hover content for the position, if anything is known."""
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if line < 0 or line >= len(raw_lines):
        return None
    raw = raw_lines[line]
    if character < 0 or character > len(raw):
        return None

    cursor = utf16_length(raw[:character])
    document = index.get(uri)
    analysis = (
        document.analysis
        if document is not None and document.analysis is not None
        else analyze(source)
    )
    logical = analysis.line_at(line)
    if logical is not None and (
        logical.kind == "continuation" or line > logical.start_line
    ):
        # A physical line in the middle of a multi-line statement may be
        # inside a string; do not resolve its text as code.
        return None

    if document is not None:
        for symbol in document.symbols:
            if symbol.line != line:
                continue
            end = symbol.character + utf16_length(symbol.source_name or symbol.name)
            if symbol.character <= cursor <= end:
                return _symbol_hover(symbol, raw_lines, uri)

        for reference in document.references:
            if reference.line != line:
                continue
            if reference.character <= cursor <= reference.end_character:
                return _reference_hover(reference, index, assets, raw_lines)

    if _inside_string_or_comment(raw[:character]):
        return None

    start_index = character
    while start_index > 0 and (
        raw[start_index - 1].isalnum() or raw[start_index - 1] in "_."
    ):
        start_index -= 1
    match = _WORD.match(raw, start_index)
    if match is None or character > match.end():
        return None
    token = match.group(0)

    builtin = api.lookup(token)
    if builtin is None:
        return None
    start = utf16_length(raw[: match.start()])
    end = start + utf16_length(token)
    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=_builtin_markdown(builtin),
        ),
        range=types.Range(
            start=types.Position(line=line, character=start),
            end=types.Position(line=line, character=end),
        ),
    )


def _symbol_hover(
    symbol: Symbol, raw_lines: list[str], current_uri: str
) -> types.Hover:
    name = symbol.source_name or symbol.name
    start = symbol.character
    end = start + utf16_length(name)
    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=_symbol_markdown(symbol, raw_lines, current_uri),
        ),
        range=types.Range(
            start=types.Position(line=symbol.line, character=start),
            end=types.Position(line=symbol.line, character=end),
        ),
    )


def _symbol_markdown(symbol: Symbol, raw_lines: list[str], current_uri: str) -> str:
    name = symbol.source_name or symbol.name
    shown = display_name(symbol)
    lines = [f"**{symbol.kind}** `{shown}`"]
    if shown != name:
        lines[0] += f" (written `{name}`)"
    if symbol.parameters:
        lines.append(f"```renpy\n{shown}({symbol.parameters})\n```")
    lines.append(_location(symbol.uri, symbol.line))
    documentation = _documentation(symbol, raw_lines, current_uri)
    if documentation:
        lines.append("---")
        lines.append(documentation)
    return "\n\n".join(lines)


def _reference_hover(
    reference: Reference,
    index: WorkspaceIndex,
    assets: AssetIndex,
    raw_lines: list[str],
) -> types.Hover | None:
    kind = reference.kind
    if kind in {"jump", "call"}:
        symbols = index.find("label", reference.name)
    elif kind in {"screen", "use"}:
        symbols = index.find("screen", reference.name)
    elif kind == "transform":
        symbols = index.find("transform", reference.name)
    elif kind == "style":
        symbols = index.find("style", reference.name)
    elif kind == "image":
        symbols = index.find("image", reference.name) + index.find(
            "layeredimage", reference.name
        )
    elif kind == "speaker":
        symbols = index.find("character", reference.name)
    elif kind == "member":
        symbols = declarations("member", reference.name, index, reference.container)
    elif kind == "class":
        symbols = declarations("member", reference.name, index)
    elif kind == "persistent":
        symbols = declarations("persistent", reference.name, index)
    elif kind == "store":
        symbols = declarations("variable", reference.name, index)
    else:
        symbols = []

    if symbols:
        value = "\n\n---\n\n".join(
            _symbol_markdown(symbol, raw_lines, reference.uri) for symbol in symbols
        )
    else:
        asset = assets.find_image(reference.name) if kind == "image" else None
        if asset is None:
            return None
        value = _asset_markdown(asset)

    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=value),
        range=types.Range(
            start=types.Position(line=reference.line, character=reference.character),
            end=types.Position(line=reference.line, character=reference.end_character),
        ),
    )


def _documentation(symbol: Symbol, raw_lines: list[str], current_uri: str) -> str:
    """Comment documentation from the symbol's own file."""
    if symbol.uri == current_uri:
        return comment_block(raw_lines, symbol.line)
    path = to_fs_path(symbol.uri)
    if path is None:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return comment_block(text.splitlines(), symbol.line)


def _asset_markdown(asset: Asset) -> str:
    return "\n\n".join(
        [
            f"**{asset.kind}** `{asset.name}`",
            f"`{asset.path}`",
        ]
    )


def _builtin_markdown(builtin: api.Builtin) -> str:
    lines = [f"**{builtin.kind}** `{builtin.signature}`"]
    lines.append(f"```renpy\n{builtin.signature}\n```")
    if builtin.documentation:
        lines.append(builtin.documentation.strip())
    return "\n\n".join(lines)


def _location(uri: str, line: int) -> str:
    path = to_fs_path(uri)
    if path is None:
        return f"line {line + 1}"
    return f"`{Path(path)}:{line + 1}`"


def _inside_string_or_comment(prefix: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in prefix:
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return True
    return quote is not None
