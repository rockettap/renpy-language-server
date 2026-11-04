"""LSP document symbols for Ren'Py declarations."""

from lsprotocol import types

from .index import (
    IndexOptions,
    Symbol,
    WorkspaceIndex,
    display_name,
    parse_document,
    utf16_length,
)

MAX_WORKSPACE_SYMBOLS = 1000

_SYMBOL_KIND = {
    "label": types.SymbolKind.Function,
    "screen": types.SymbolKind.Class,
    "transform": types.SymbolKind.Constructor,
    "image": types.SymbolKind.Field,
    "character": types.SymbolKind.Variable,
    "style": types.SymbolKind.Interface,
    "layeredimage": types.SymbolKind.Field,
    "variable": types.SymbolKind.Variable,
    "class": types.SymbolKind.Class,
    "callable": types.SymbolKind.Function,
    "method": types.SymbolKind.Method,
    "field": types.SymbolKind.Field,
    "property": types.SymbolKind.Property,
    "store": types.SymbolKind.Namespace,
    "persistent": types.SymbolKind.Variable,
    "testcase": types.SymbolKind.Function,
    "translation": types.SymbolKind.String,
}

_CONTAINER_KINDS = frozenset({"class", "store"})


def document_symbols(
    uri: str,
    source: str,
    version: int | None = None,
    options: IndexOptions | None = None,
) -> list[types.DocumentSymbol]:
    """Build a symbol tree for one document."""
    document = parse_document(uri, source, version, options)
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    built: list[tuple[Symbol, types.DocumentSymbol]] = []

    for symbol in document.symbols:
        range_end = _line_end(raw_lines, symbol.end_line)
        built.append(
            (
                symbol,
                types.DocumentSymbol(
                    name=symbol.name,
                    detail=symbol.detail,
                    kind=_SYMBOL_KIND[symbol.kind],
                    range=types.Range(
                        start=types.Position(line=symbol.line, character=0),
                        end=types.Position(line=symbol.end_line, character=range_end),
                    ),
                    selection_range=_selection_range(symbol),
                ),
            )
        )

    nodes = {id(symbol): node for symbol, node in built}
    top: list[types.DocumentSymbol] = []
    for symbol, node in built:
        parent = _container_symbol(symbol, [item for item, _ in built])
        if parent is None:
            top.append(node)
            continue
        parent_node = nodes[id(parent)]
        children = list(parent_node.children or [])
        children.append(node)
        parent_node.children = children
    return top


def workspace_symbols(
    index: WorkspaceIndex,
    query: str,
    limit: int = MAX_WORKSPACE_SYMBOLS,
) -> list[types.SymbolInformation]:
    """Search the workspace index for symbols matching ``query``.

    Matching is case-insensitive. Exact names rank first, then prefix matches,
    then substring matches, so typing ``start`` surfaces ``start`` before
    ``chapter_start`` and ``restart``.
    """
    needle = query.strip().casefold()
    ranked: list[tuple[int, Symbol]] = []
    for symbol in index.all_symbols():
        qualified = display_name(symbol).casefold()
        name = symbol.name.casefold()
        if needle:
            if name == needle:
                rank = 0
            elif name.startswith(needle):
                rank = 1
            elif qualified.startswith(needle):
                rank = 2
            elif needle in qualified:
                rank = 3
            else:
                continue
        else:
            rank = 4
        ranked.append((rank, symbol))

    ranked.sort(
        key=lambda item: (
            item[0],
            display_name(item[1]).casefold(),
            item[1].uri,
            item[1].line,
            item[1].character,
        )
    )
    return [
        types.SymbolInformation(
            name=symbol.name,
            kind=_SYMBOL_KIND[symbol.kind],
            location=types.Location(uri=symbol.uri, range=_selection_range(symbol)),
            container_name=symbol.container or None,
        )
        for _, symbol in ranked[:limit]
    ]


def _container_symbol(symbol: Symbol, symbols: list[Symbol]) -> Symbol | None:
    """Closest class/store symbol whose body contains ``symbol``."""
    if not symbol.container:
        return None
    candidates = [
        item
        for item in symbols
        if item.kind in _CONTAINER_KINDS
        and item.name == symbol.container
        and item.line <= symbol.line <= item.end_line
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.line)


def _selection_range(symbol: Symbol) -> types.Range:
    written = symbol.source_name or symbol.name
    return types.Range(
        start=types.Position(line=symbol.line, character=symbol.character),
        end=types.Position(
            line=symbol.line,
            character=symbol.character + utf16_length(written),
        ),
    )


def _line_end(raw_lines: list[str], line: int) -> int:
    if line < 0 or line >= len(raw_lines):
        return 0
    return utf16_length(raw_lines[line])
