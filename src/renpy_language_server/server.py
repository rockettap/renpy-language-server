"""LSP server. Stdout carries the protocol, so log to stderr only."""

import asyncio
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path
from pygls.workspace.text_document import TextDocument

from . import __version__
from .assets import AUDIO_SUFFIXES, IMAGE_SUFFIXES, Asset, AssetIndex
from .code_actions import code_actions_for
from .completion import Completion, complete
from .definition import find_definition, find_image_definition
from .diagnostics import diagnostics_for_document
from .edits import Edit, compute_edits, compute_edits_in_range
from .folding import folding_ranges
from .formatter import FormatOptions, format_source
from .hover import hover_at
from .index import (
    SOURCE_SUFFIXES,
    IndexOptions,
    Symbol,
    WorkspaceIndex,
    enclosing_python_class,
    scan_workspace,
    utf16_length,
    workspace_paths,
)
from .positions import client_position
from .quotes import normalize_quotes
from .references import references_at
from .rename import document_highlights_at, prepare_rename_at, rename_at
from .semantic import LEGEND
from .semantic import semantic_tokens as semantic_tokens_for
from .settings import Settings, merge_settings, settings_from_initialize
from .signature import signature_at
from .symbols import document_symbols, workspace_symbols

logging.basicConfig(
    stream=sys.stderr, level=logging.INFO, format="renpy-language-server: %(message)s"
)
log = logging.getLogger("renpy-language-server")

# pygls logs every JSON-RPC frame at INFO, including full document contents.
# Keep normal runs quiet; set RENPY_LANGUAGE_SERVER_DEBUG=1 to see the protocol traffic.
_log_level = (
    logging.DEBUG if os.environ.get("RENPY_LANGUAGE_SERVER_DEBUG") else logging.WARNING
)
logging.getLogger("pygls").setLevel(_log_level)
if _log_level == logging.DEBUG:
    log.setLevel(logging.DEBUG)

server = LanguageServer("renpy-language-server", f"v{__version__}")

_settings = Settings()
_index = WorkspaceIndex()
_assets = AssetIndex()
_roots: list[Path] = []
_diagnostic_timers: dict[str, asyncio.TimerHandle] = {}


def _index_options(settings: Settings | None = None) -> IndexOptions:
    current = settings or _settings
    return IndexOptions(
        extended=current.extended_index,
        members=current.member_references,
    )


@server.feature(types.INITIALIZE)
async def initialize(ls: LanguageServer, params: types.InitializeParams) -> None:
    """Load settings, then build the workspace index before serving requests."""
    global _settings, _index, _assets, _roots

    _settings = settings_from_initialize(params)
    _index = WorkspaceIndex(_index_options())
    _assets = AssetIndex()

    uris = [folder.uri for folder in ls.workspace.folders.values()]
    if ls.workspace.root_uri is not None:
        uris.append(ls.workspace.root_uri)
    _roots = workspace_paths(uris)
    if _roots:
        documents = await asyncio.to_thread(scan_workspace, _roots, _index.options)
        _index.merge(documents)
        await asyncio.to_thread(_assets.scan, _roots)


@server.feature(types.INITIALIZED)
def initialized(ls: LanguageServer, params: types.InitializedParams) -> None:
    """Publish workspace diagnostics once the client is ready to receive them."""
    _publish_all_diagnostics(ls)


@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
async def did_change_configuration(
    ls: LanguageServer, params: types.DidChangeConfigurationParams
) -> None:
    """Merge client settings over the current defaults."""
    global _settings, _index
    previous_mode = _settings.diagnostics_mode
    previous = _index_options()
    _settings = merge_settings(_settings, params.settings)
    current = _index_options()
    if current != previous:
        _index = WorkspaceIndex(current)
        if _roots:
            documents = await asyncio.to_thread(scan_workspace, _roots, _index.options)
            _index.merge(documents)
        _reindex_open(ls)
    _publish_all_diagnostics(ls)
    if previous_mode == "workspace" and _settings.diagnostics_mode != "workspace":
        _clear_closed_diagnostics(ls)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    document = params.text_document
    _index.update(document.uri, document.text, document.version)
    _publish_diagnostics(ls, document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    document = ls.workspace.get_text_document(params.text_document.uri)
    _index.update(document.uri, document.source, document.version)
    _schedule_diagnostics(ls, document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    """Keep the last parse so closed files stay available for navigation."""
    _cancel_timer(params.text_document.uri)
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
    )


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    document = ls.workspace.get_text_document(params.text_document.uri)
    _index.update(document.uri, document.source, document.version)
    if _settings.diagnostics_mode == "workspace":
        _publish_all_diagnostics(ls)
    else:
        _publish_diagnostics(ls, document.uri)


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(
    ls: LanguageServer, params: types.DidChangeWatchedFilesParams
) -> None:
    assets_changed = False
    removed: list[str] = []
    for event in params.changes:
        uri = event.uri
        path = to_fs_path(uri)
        suffix = Path(path).suffix.lower() if path is not None else ""
        if suffix in IMAGE_SUFFIXES or suffix in AUDIO_SUFFIXES:
            assets_changed = True
        if event.type == types.FileChangeType.Deleted:
            _index.remove(uri)
            removed.append(uri)
            continue
        if path is None or suffix not in SOURCE_SUFFIXES:
            continue
        try:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _index.update(uri, source)
    if assets_changed:
        _assets.scan(_roots)
    _publish_all_diagnostics(ls)
    for uri in removed:
        _clear_diagnostics(ls, uri)


@server.feature(types.WORKSPACE_DID_CHANGE_WORKSPACE_FOLDERS)
async def did_change_workspace_folders(
    ls: LanguageServer, params: types.DidChangeWorkspaceFoldersParams
) -> None:
    global _roots

    added = workspace_paths(folder.uri for folder in params.event.added or [])
    removed = workspace_paths(folder.uri for folder in params.event.removed or [])

    removed_roots = tuple(path.resolve() for path in removed)
    removed_uris: list[str] = []
    if removed_roots:
        for uri in _index.uris():
            path = to_fs_path(uri)
            if path is None:
                continue
            candidate = Path(path).resolve()
            if any(
                candidate == root or root in candidate.parents for root in removed_roots
            ):
                _index.remove(uri)
                removed_uris.append(uri)

    if added:
        documents = await asyncio.to_thread(scan_workspace, added, _index.options)
        _index.merge(documents)
        _reindex_open(ls)

    _roots = workspace_paths(
        [folder.uri for folder in ls.workspace.folders.values()]
        + ([ls.workspace.root_uri] if ls.workspace.root_uri is not None else [])
    )
    await asyncio.to_thread(_assets.scan, _roots)
    _publish_all_diagnostics(ls)
    for uri in removed_uris:
        _clear_diagnostics(ls, uri)


def _reindex_open(ls: LanguageServer) -> None:
    for document in ls.workspace.text_documents.values():
        _index.update(document.uri, document.source, document.version)


def _publish_all_open(ls: LanguageServer) -> None:
    for document in ls.workspace.text_documents.values():
        _publish_diagnostics(ls, document.uri)


def _publish_all_diagnostics(ls: LanguageServer) -> None:
    """Publish diagnostics for every indexed file, or just the open files."""
    if _settings.diagnostics_mode != "workspace":
        _publish_all_open(ls)
        return

    for uri in _index.uris():
        _publish_diagnostics(ls, uri)


def _clear_closed_diagnostics(ls: LanguageServer) -> None:
    open_uris = set(ls.workspace.text_documents)
    for uri in _index.uris():
        if uri not in open_uris:
            _clear_diagnostics(ls, uri)


def _clear_diagnostics(ls: LanguageServer, uri: str) -> None:
    _cancel_timer(uri)
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )


def _publish_diagnostics(ls: LanguageServer, uri: str) -> None:
    _cancel_timer(uri)
    document = ls.workspace.text_documents.get(uri)
    if document is not None:
        source = document.source
        version = document.version
    else:
        indexed = _index.get(uri)
        if indexed is None:
            _clear_diagnostics(ls, uri)
            return
        source = indexed.source
        version = indexed.version

    try:
        diagnostics = diagnostics_for_document(
            source,
            _index,
            _settings,
            uri,
            _assets,
        )
    except Exception:
        log.exception("diagnostics failed for %s", uri)
        diagnostics = []

    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=uri,
            diagnostics=diagnostics,
            version=version,
        )
    )


def _schedule_diagnostics(ls: LanguageServer, uri: str) -> None:
    _cancel_timer(uri)
    loop = asyncio.get_running_loop()
    _diagnostic_timers[uri] = loop.call_later(0.25, _publish_diagnostics, ls, uri)


def _cancel_timer(uri: str) -> None:
    timer = _diagnostic_timers.pop(uri, None)
    if timer is not None:
        timer.cancel()


def _completion_symbols(include_assets: bool = True) -> dict[str, list[Completion]]:
    """Convert indexed symbols into completion items grouped by kind."""
    result: dict[str, list[Completion]] = {
        "label": [],
        "image": [],
        "screen": [],
        "character": [],
        "variable": [],
        "persistent": [],
        "class": [],
        "callable": [],
        "transform": [],
        "style": [],
    }
    for symbol in _index.all_symbols():
        kind = "image" if symbol.kind == "layeredimage" else symbol.kind
        if kind in {"method", "field", "property"} or (
            kind in {"class", "callable"} and symbol.container
        ):
            key = f"member:{symbol.container}"
        else:
            key = kind
        path = to_fs_path(symbol.uri)
        filename = Path(path).name if path is not None else symbol.uri
        detail = symbol.detail or kind
        result.setdefault(key, []).append(
            Completion(
                label=symbol.name,
                kind=kind,
                detail=detail,
                documentation=(f"{kind} `{_display_symbol(symbol)}` in {filename}"),
            )
        )

    if include_assets:
        seen = {item.label for item in result["image"]}
        for asset in _assets.images():
            if asset.name in seen:
                continue
            seen.add(asset.name)
            result["image"].append(
                Completion(
                    label=asset.name,
                    kind="image",
                    detail="image file",
                    documentation=f"Automatic image `{asset.name}` at {asset.path}",
                )
            )

        result["audio"] = [
            Completion(
                label=asset.name,
                kind="audio",
                detail="audio file",
                documentation=f"Automatic audio `{asset.name}` at {asset.path}",
                insert_text=f'"{asset.name}"',
            )
            for asset in _assets.audio()
        ]
    else:
        result.setdefault("audio", [])
    return result


def _display_symbol(symbol: Symbol) -> str:
    return f"{symbol.container}.{symbol.name}" if symbol.container else symbol.name


_COMPLETION_KIND = {
    "keyword": types.CompletionItemKind.Keyword,
    "label": types.CompletionItemKind.Function,
    "image": types.CompletionItemKind.File,
    "screen": types.CompletionItemKind.Class,
    "character": types.CompletionItemKind.Variable,
    "class": types.CompletionItemKind.Class,
    "function": types.CompletionItemKind.Function,
    "callable": types.CompletionItemKind.Function,
    "builtin": types.CompletionItemKind.Function,
    "method": types.CompletionItemKind.Method,
    "action": types.CompletionItemKind.Value,
    "transition": types.CompletionItemKind.Value,
    "transform": types.CompletionItemKind.Function,
    "style": types.CompletionItemKind.Class,
    "attribute": types.CompletionItemKind.Property,
    "audio": types.CompletionItemKind.File,
    "value": types.CompletionItemKind.Value,
    "field": types.CompletionItemKind.Field,
    "property": types.CompletionItemKind.Property,
    "persistent": types.CompletionItemKind.Variable,
    "variable": types.CompletionItemKind.Variable,
}

_COMPLETION_SORT = {
    "keyword": "0",
    "character": "1",
    "label": "2",
    "image": "3",
    "screen": "4",
    "class": "5",
    "function": "5",
    "callable": "5",
    "builtin": "5",
    "transform": "5",
    "style": "6",
    "method": "5",
    "field": "6",
    "property": "6",
    "attribute": "6",
    "action": "7",
    "transition": "7",
    "persistent": "6",
    "variable": "7",
    "audio": "3",
    "value": "8",
}


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
def code_action(
    ls: LanguageServer, params: types.CodeActionParams
) -> list[types.CodeAction]:
    if not _settings.code_actions:
        return []
    only = params.context.only
    if only and not any(
        kind == types.CodeActionKind.QuickFix or kind.startswith("quickfix")
        for kind in only
    ):
        return []

    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = diagnostics_for_document(
        doc.source,
        _index,
        _settings,
        doc.uri,
        _assets,
    )
    return code_actions_for(
        doc.uri,
        doc.source,
        params.range,
        diagnostics,
        _settings.indent,
    )


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=[" ", ":", ".", "(", "@", "-"]),
)
def completion(
    ls: LanguageServer, params: types.CompletionParams
) -> list[types.CompletionItem]:
    if not _settings.completion:
        return []

    doc = ls.workspace.get_text_document(params.text_document.uri)
    source = doc.source
    offset = doc.offset_at_position(params.position)
    line_start = source.rfind("\n", 0, offset) + 1
    prefix = source[line_start:offset]
    line_index = source.count("\n", 0, line_start)

    result = complete(
        source,
        prefix,
        _completion_symbols(_settings.automatic_assets),
        enclosing_python_class(source, line_index),
        line_index,
    )
    if not result.items:
        return []

    replace = types.Range(
        start=client_position(doc, source, line_index, result.replace_start),
        end=params.position,
    )
    return [
        types.CompletionItem(
            label=item.label,
            kind=_COMPLETION_KIND.get(item.kind, types.CompletionItemKind.Text),
            detail=item.detail,
            documentation=(
                types.MarkupContent(
                    kind=types.MarkupKind.Markdown, value=item.documentation
                )
                if item.documentation
                else None
            ),
            filter_text=item.label,
            sort_text=item.sort_text
            or _COMPLETION_SORT.get(item.kind, "9") + item.label,
            text_edit=types.TextEdit(
                range=replace, new_text=item.insert_text or item.label
            ),
        )
        for item in result.items
    ]


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL, LEGEND)
def semantic_tokens(
    ls: LanguageServer, params: types.SemanticTokensParams
) -> types.SemanticTokens:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return semantic_tokens_for(
        doc.uri,
        doc.source,
        enabled=_settings.semantic_tokens,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(
    ls: LanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol]:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return document_symbols(doc.uri, doc.source, doc.version, _index_options())


@server.feature(types.WORKSPACE_SYMBOL)
def workspace_symbol(
    ls: LanguageServer, params: types.WorkspaceSymbolParams
) -> list[types.SymbolInformation]:
    if not _settings.workspace_symbols:
        return []
    return workspace_symbols(_index, params.query)


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(
    ls: LanguageServer, params: types.DefinitionParams
) -> list[types.Location]:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    server_position = doc.position_from_client_units(params.position)

    symbols = find_definition(
        doc.source,
        server_position.line,
        server_position.character,
        _index,
    )
    if not symbols:
        image = find_image_definition(
            doc.source,
            server_position.line,
            server_position.character,
            _index,
            _assets,
        )
        if image is None:
            return []
        if isinstance(image, Asset):
            return [
                types.Location(
                    uri=image.path.as_uri(),
                    range=types.Range(
                        start=types.Position(line=0, character=0),
                        end=types.Position(line=0, character=0),
                    ),
                )
            ]
        symbols = [image]

    return [
        types.Location(
            uri=symbol.uri,
            range=types.Range(
                start=types.Position(
                    line=symbol.line,
                    character=symbol.character,
                ),
                end=types.Position(
                    line=symbol.line,
                    character=symbol.character
                    + utf16_length(symbol.source_name or symbol.name),
                ),
            ),
        )
        for symbol in symbols
    ]


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references(
    ls: LanguageServer, params: types.ReferenceParams
) -> list[types.Location] | None:
    if not _settings.references:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return references_at(
        doc.uri,
        doc.source,
        position.line,
        position.character,
        _index,
        params.context.include_declaration,
    )


@server.feature(
    types.TEXT_DOCUMENT_SIGNATURE_HELP,
    types.SignatureHelpOptions(trigger_characters=["(", ",", "="]),
)
def signature_help(
    ls: LanguageServer, params: types.SignatureHelpParams
) -> types.SignatureHelp | None:
    if not _settings.signature:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return signature_at(
        doc.source,
        position.line,
        position.character,
        _index,
    )


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: LanguageServer, params: types.HoverParams) -> types.Hover | None:
    if not _settings.hover:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return hover_at(
        doc.uri,
        doc.source,
        position.line,
        position.character,
        _index,
        _assets,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(
    ls: LanguageServer, params: types.DocumentHighlightParams
) -> list[types.DocumentHighlight] | None:
    if not _settings.highlight:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return document_highlights_at(
        doc.uri,
        doc.source,
        position.line,
        position.character,
        _index,
    )


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(
    ls: LanguageServer, params: types.PrepareRenameParams
) -> types.Range | None:
    if not _settings.rename:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return prepare_rename_at(
        doc.uri,
        doc.source,
        position.line,
        position.character,
        _index,
    )


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename(
    ls: LanguageServer, params: types.RenameParams
) -> types.WorkspaceEdit | None:
    if not _settings.rename:
        return None
    doc = ls.workspace.get_text_document(params.text_document.uri)
    position = doc.position_from_client_units(params.position)
    return rename_at(
        doc.uri,
        doc.source,
        position.line,
        position.character,
        params.new_name,
        _index,
    )


@server.feature(types.TEXT_DOCUMENT_FOLDING_RANGE)
def folding_range(
    ls: LanguageServer, params: types.FoldingRangeParams
) -> list[types.FoldingRange]:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return [
        types.FoldingRange(start_line=item.start_line, end_line=item.end_line)
        for item in folding_ranges(doc.source)
    ]


def _format_options(options: types.FormattingOptions) -> FormatOptions:
    indent = options.tab_size if options.tab_size > 0 else _settings.indent
    return FormatOptions(
        indent=indent,
        max_blank_lines=_settings.max_blank_lines,
        align_equals=_settings.align_equals,
        normalize_spacing=_settings.normalize_spacing,
        normalize_quotes=_settings.normalize_quotes,
        format_python=_settings.format_python,
    )


def _text_edits(
    doc: TextDocument,
    source: str,
    edits: list[Edit],
) -> list[types.TextEdit]:
    return [
        types.TextEdit(
            range=types.Range(
                start=client_position(doc, source, edit.start_line, edit.start_char),
                end=client_position(doc, source, edit.end_line, edit.end_char),
            ),
            new_text=edit.new_text,
        )
        for edit in edits
    ]


@server.feature(types.TEXT_DOCUMENT_FORMATTING)
def formatting(
    ls: LanguageServer, params: types.DocumentFormattingParams
) -> list[types.TextEdit]:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    old = doc.source
    new = format_source(old, _format_options(params.options))
    return _text_edits(doc, old, compute_edits(old, new))


@server.feature(types.TEXT_DOCUMENT_RANGE_FORMATTING)
def range_formatting(
    ls: LanguageServer, params: types.DocumentRangeFormattingParams
) -> list[types.TextEdit]:
    doc = ls.workspace.get_text_document(params.text_document.uri)
    old = doc.source
    options = _format_options(params.options)
    prepared = old
    if options.normalize_quotes:
        # Rewrite quotes on the original text, restricted to the requested
        # lines, so a multi-line literal is never converted on one side only.
        # The delimiters keep their length, so line numbers stay valid.
        allowed = range(params.range.start.line, params.range.end.line + 1)
        prepared = normalize_quotes(old, allowed)
        options = replace(options, normalize_quotes=False)
    new = format_source(prepared, options)
    edits = compute_edits_in_range(
        old,
        new,
        params.range.start.line,
        params.range.end.line,
    )
    return _text_edits(doc, old, edits)


def run() -> None:
    log.info("starting (stdio)")
    server.start_io()
