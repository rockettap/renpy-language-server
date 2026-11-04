"""Shared symbol resolution for navigation and refactoring providers.

This module locates the symbol under a cursor, resolves it to a declaration
family, and enumerates every occurrence. Rename, definition, references and
document highlights all build on it, so they agree on what a symbol is and
where it is written.
"""

import re
from dataclasses import dataclass

from .analysis import Analysis, analyze
from .index import (
    DocumentIndex,
    Reference,
    Symbol,
    WorkspaceIndex,
    parse_document,
    utf16_length,
)

_INTERPOLATION_TOKEN = re.compile(r"[A-Za-z_]\w*")
_TOKEN = re.compile(r"[A-Za-z_]\w*")
_SCREEN_VARIABLE = re.compile(r"^(?:default|define)\s+([A-Za-z_]\w*)")

_STATEMENT_WORDS = frozenset(
    {
        "add",
        "at",
        "behind",
        "call",
        "camera",
        "centered",
        "default",
        "define",
        "elif",
        "else",
        "expression",
        "hide",
        "if",
        "image",
        "init",
        "jump",
        "label",
        "layeredimage",
        "layer",
        "menu",
        "nvl",
        "onlayer",
        "pass",
        "pause",
        "play",
        "python",
        "queue",
        "return",
        "scene",
        "screen",
        "show",
        "stop",
        "style",
        "transform",
        "translate",
        "use",
        "voice",
        "while",
        "window",
        "with",
        "zorder",
    }
)
_AUDIO_WORDS = frozenset(
    {
        "audio",
        "fadein",
        "fadeout",
        "from",
        "if_changed",
        "loop",
        "music",
        "noloop",
        "relative",
        "sound",
        "to",
        "voice",
    }
)
_CLAUSE_WORDS = frozenset({"as", "at", "behind", "onlayer", "with", "zorder"})
_LANGUAGE_WORDS = frozenset({"layeredimage", "screen", "style", "transform"})

FAMILIES = frozenset(
    {
        "label",
        "screen",
        "transform",
        "image",
        "character",
        "style",
        "variable",
        "member",
        "persistent",
        "store",
        "testcase",
        "translation",
    }
)

MEMBER_KINDS = frozenset({"class", "callable", "method", "field", "property"})

REFERENCE_KINDS: dict[str, frozenset[str]] = {
    "screen": frozenset({"screen", "use"}),
    "transform": frozenset({"transform"}),
    "image": frozenset({"image"}),
    "character": frozenset({"speaker"}),
    "style": frozenset({"style"}),
    "member": frozenset({"member", "class"}),
    "persistent": frozenset({"persistent"}),
}

_KIND_FAMILY = {
    "layeredimage": "image",
    "class": "member",
    "callable": "member",
    "method": "member",
    "field": "member",
    "property": "member",
}


@dataclass(frozen=True)
class Located:
    """The symbol or reference span under the cursor."""

    symbol: Symbol | None
    reference: Reference | None
    start: int
    end: int
    variable: str | None = None


@dataclass(frozen=True)
class Target:
    """A located name resolved to a declaration family."""

    family: str
    name: str
    located: Located
    container: str = ""


@dataclass(frozen=True)
class Occurrence:
    """One written occurrence of a target."""

    uri: str
    line: int
    start: int
    end: int
    write: bool = False


@dataclass(frozen=True)
class _VariableSpan:
    line: int
    start: int
    end: int
    name: str
    quoted: bool = False


def locate(
    uri: str,
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> Located | None:
    """Return the indexed symbol or reference under ``line``/``character``."""
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if line < 0 or line >= len(raw_lines):
        return None
    raw = raw_lines[line]
    if character < 0 or character > len(raw):
        return None

    cursor = utf16_length(raw[:character])
    document = index.get(uri)
    if document is None:
        document = parse_document(uri, source, options=index.options)
    analysis = document.analysis if document.analysis is not None else analyze(source)

    logical = analysis.line_at(line)
    continuation = logical is not None and (
        logical.kind == "continuation" or line > logical.start_line
    )

    if not continuation:
        for symbol in document.symbols:
            if symbol.line != line:
                continue
            end = symbol.character + utf16_length(symbol.source_name or symbol.name)
            if symbol.character <= cursor <= end:
                return Located(symbol, None, symbol.character, end)

        for reference in document.references:
            if reference.line != line:
                continue
            if reference.character <= cursor <= reference.end_character:
                return Located(
                    None,
                    reference,
                    reference.character,
                    reference.end_character,
                )

    variable = _variable_span_at(source, line, cursor, document)
    if variable is not None and index.find("variable", variable.name):
        return Located(None, None, variable.start, variable.end, variable=variable.name)
    return None


def target(located: Located, index: WorkspaceIndex) -> Target | None:
    """Resolve a located span to a family only when a declaration exists."""
    if located.symbol is not None:
        symbol = located.symbol
        family = _KIND_FAMILY.get(symbol.kind, symbol.kind)
        if family not in FAMILIES:
            return None
        return Target(family, symbol.name, located, symbol.container)

    if located.variable is not None:
        return Target("variable", located.variable, located)

    reference = located.reference
    if reference is None:
        return None
    container = reference.container
    if reference.kind in {"jump", "call"}:
        family = "label"
    elif reference.kind in {"screen", "use"}:
        family = "screen"
    elif reference.kind == "transform":
        family = "transform"
    elif reference.kind == "image":
        family = "image"
    elif reference.kind == "speaker":
        family = "character"
    elif reference.kind == "style":
        family = "style"
    elif reference.kind == "member":
        family = "member"
    elif reference.kind == "class":
        family = "member"
        container = ""
    elif reference.kind == "persistent":
        family = "persistent"
    elif reference.kind == "store":
        family = "variable"
        container = ""
    else:
        return None

    if not declarations(family, reference.name, index, container):
        return None
    return Target(family, reference.name, located, container)


def declarations(
    family: str, name: str, index: WorkspaceIndex, container: str = ""
) -> list[Symbol]:
    """Return declarations for one family, including layered images."""
    if family == "image":
        return index.find("image", name) + index.find("layeredimage", name)

    if family == "member":
        result: list[Symbol] = []
        for kind in MEMBER_KINDS:
            result.extend(
                symbol
                for symbol in index.find(kind, name)  # type: ignore[arg-type]
                if symbol.container == (container or "")
            )
        return result

    if family == "persistent":
        return [
            symbol
            for symbol in index.find("persistent", name)  # type: ignore[arg-type]
            if symbol.container == "persistent"
        ]

    symbols = index.find(family, name)  # type: ignore[arg-type]
    if container:
        symbols = [symbol for symbol in symbols if symbol.container == container]
    return symbols


def occurrences(
    target: Target, index: WorkspaceIndex, uri: str | None = None
) -> list[Occurrence]:
    """Return every declaration and reference of ``target``.

    When ``uri`` is given, only occurrences in that document are returned.
    ``Occurrence.write`` distinguishes declarations from uses.
    """
    if target.family == "variable":
        return _variable_occurrences(target, index, uri)

    found: dict[tuple[str, int, int, int], Occurrence] = {}
    if target.family == "label":
        _label_occurrences(target, index, found, uri)
        return _sorted_occurrences(found)

    for symbol in declarations(target.family, target.name, index, target.container):
        if uri is not None and symbol.uri != uri:
            continue
        written = symbol.source_name or symbol.name
        _add_occurrence(
            found,
            Occurrence(
                symbol.uri,
                symbol.line,
                symbol.character,
                symbol.character + utf16_length(written),
                write=True,
            ),
        )

    reference_kinds = REFERENCE_KINDS.get(target.family, frozenset())
    for reference in index.all_references():
        if uri is not None and reference.uri != uri:
            continue
        if (
            reference.kind in reference_kinds
            and reference.name == target.name
            and reference.container == target.container
        ):
            _add_occurrence(
                found,
                Occurrence(
                    reference.uri,
                    reference.line,
                    reference.character,
                    reference.end_character,
                ),
            )
    return _sorted_occurrences(found)


def _variable_occurrences(
    target: Target, index: WorkspaceIndex, uri: str | None = None
) -> list[Occurrence]:
    found: dict[tuple[str, int, int, int], Occurrence] = {}
    for symbol in index.find("variable", target.name):
        if uri is not None and symbol.uri != uri:
            continue
        written = symbol.source_name or symbol.name
        _add_occurrence(
            found,
            Occurrence(
                symbol.uri,
                symbol.line,
                symbol.character,
                symbol.character + utf16_length(written),
                write=True,
            ),
        )

    blocked = _blocked_spans(index, uri)
    for document_uri in [uri] if uri is not None else index.uris():
        document = index.get(document_uri)
        if document is None:
            continue
        intervals = blocked.get(document_uri, {})
        for span in _variable_spans(document.source, document):
            if span.name != target.name:
                continue
            if _overlaps(intervals.get(span.line, []), span.start, span.end):
                continue
            _add_occurrence(
                found,
                Occurrence(document_uri, span.line, span.start, span.end),
            )

    for reference in index.all_references():
        if reference.kind != "store" or reference.name != target.name:
            continue
        if uri is not None and reference.uri != uri:
            continue
        _add_occurrence(
            found,
            Occurrence(
                reference.uri,
                reference.line,
                reference.character,
                reference.end_character,
            ),
        )
    return _sorted_occurrences(found)


def _label_occurrences(
    target: Target,
    index: WorkspaceIndex,
    found: dict[tuple[str, int, int, int], Occurrence],
    uri: str | None,
) -> None:
    if "." in target.name:
        for symbol in index.by_kind("label"):
            if symbol.name != target.name:
                continue
            if uri is not None and symbol.uri != uri:
                continue
            written = symbol.source_name or symbol.name
            _add_occurrence(
                found,
                Occurrence(
                    symbol.uri,
                    symbol.line,
                    symbol.character,
                    symbol.character + utf16_length(written),
                    write=True,
                ),
            )
        for reference in index.all_references():
            if uri is not None and reference.uri != uri:
                continue
            if reference.kind in {"jump", "call"} and reference.name == target.name:
                _add_occurrence(
                    found,
                    Occurrence(
                        reference.uri,
                        reference.line,
                        reference.character,
                        reference.end_character,
                    ),
                )
        return

    old = target.name
    for symbol in index.by_kind("label"):
        if uri is not None and symbol.uri != uri:
            continue
        written = symbol.source_name or symbol.name
        if symbol.name == old or (
            symbol.name.startswith(f"{old}.") and not written.startswith(".")
        ):
            _add_occurrence(
                found,
                Occurrence(
                    symbol.uri,
                    symbol.line,
                    symbol.character,
                    symbol.character + utf16_length(written),
                    write=True,
                ),
            )

    for reference in index.all_references():
        if uri is not None and reference.uri != uri:
            continue
        if reference.kind not in {"jump", "call"}:
            continue
        if reference.name != old and not reference.name.startswith(f"{old}."):
            continue
        if reference.source_name.startswith("."):
            continue
        _add_occurrence(
            found,
            Occurrence(
                reference.uri,
                reference.line,
                reference.character,
                reference.end_character,
            ),
        )


def _add_occurrence(
    found: dict[tuple[str, int, int, int], Occurrence],
    item: Occurrence,
) -> None:
    key = (item.uri, item.line, item.start, item.end)
    existing = found.get(key)
    if existing is None or (item.write and not existing.write):
        found[key] = item


def _sorted_occurrences(
    found: dict[tuple[str, int, int, int], Occurrence],
) -> list[Occurrence]:
    return sorted(found.values(), key=lambda item: (item.uri, item.line, item.start))


def _blocked_spans(
    index: WorkspaceIndex,
    uri: str | None = None,
) -> dict[str, dict[int, list[tuple[int, int]]]]:
    """Spans that belong to non-variable symbols and references."""
    result: dict[str, dict[int, list[tuple[int, int]]]] = {}
    for document_uri in [uri] if uri is not None else index.uris():
        document = index.get(document_uri)
        if document is None:
            continue
        lines: dict[int, list[tuple[int, int]]] = {}

        for symbol in document.symbols:
            if symbol.kind == "variable":
                continue
            written = symbol.source_name or symbol.name
            _block_span(
                lines,
                symbol.line,
                symbol.character,
                symbol.character + utf16_length(written),
            )
        for reference in document.references:
            _block_span(
                lines,
                reference.line,
                reference.character,
                reference.end_character,
            )
        for spans in lines.values():
            spans.sort()
        result[document_uri] = lines
    return result


def _block_span(
    lines: dict[int, list[tuple[int, int]]], line: int, start: int, end: int
) -> None:
    lines.setdefault(line, []).append((start, end))


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(left < end and start < right for left, right in spans)


def _variable_span_at(
    source: str,
    line: int,
    cursor: int,
    document: DocumentIndex | None = None,
) -> _VariableSpan | None:
    for span in _variable_spans(source, document):
        if span.line == line and span.start <= cursor <= span.end:
            return span
    return None


def _variable_spans(
    source: str, document: DocumentIndex | None = None
) -> list[_VariableSpan]:
    """Identifier spans outside strings and comments, minus syntax tokens."""
    spans: list[_VariableSpan] = []
    line = 0
    line_start = 0
    index = 0
    length = len(source)
    quote: str | None = None
    triple = False
    escaped = False

    while index < length:
        char = source[index]
        if char == "\n":
            line += 1
            line_start = index + 1
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if char == "\\":
                escaped = True
                index += 1
                continue
            if char == "[":
                if source.startswith("[[", index):
                    index += 2
                    continue
                close = source.find("]", index + 1)
                if close >= 0 and "\n" not in source[index:close]:
                    spans.extend(
                        _interpolation_spans(source, index + 1, close, line, line_start)
                    )
                    index = close + 1
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
            while index < length and source[index] != "\n":
                index += 1
            continue
        if char in "\"'":
            triple = source.startswith(char * 3, index)
            quote = char
            index += 3 if triple else 1
            continue
        if char.isalpha() or char == "_":
            end_index = index + 1
            while end_index < length and (
                source[end_index].isalnum() or source[end_index] == "_"
            ):
                end_index += 1
            token = source[index:end_index]
            previous = _previous_significant(source, index)
            if previous != "." and not _keyword_argument(source, end_index, previous):
                start = utf16_length(source[line_start:index])
                spans.append(
                    _VariableSpan(line, start, start + utf16_length(token), token)
                )
            index = end_index
            continue
        index += 1
    return _filter_variable_spans(spans, source, document)


def _filter_variable_spans(
    spans: list[_VariableSpan],
    source: str,
    document: DocumentIndex | None,
) -> list[_VariableSpan]:
    """Remove spans that are Ren'Py syntax, speakers or screen locals."""
    analysis = analyze(source)
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    skip = _syntax_skip_spans(analysis, raw_lines)
    speaker_limits = _speaker_attribute_limits(document)
    screen_locals = _screen_local_variables(analysis)

    result: list[_VariableSpan] = []
    for span in spans:
        if not span.quoted and (span.line, span.start) in skip:
            continue
        limit = speaker_limits.get(span.line)
        if limit is not None and not span.quoted and span.start >= limit:
            continue
        if any(
            span.name == name and start <= span.line <= end
            for name, start, end in screen_locals
        ):
            continue
        result.append(span)
    return result


def _speaker_attribute_limits(
    document: DocumentIndex | None,
) -> dict[int, int]:
    """End column of the speaker on each dialogue line."""
    if document is None:
        return {}
    limits: dict[int, int] = {}
    for reference in document.references:
        if reference.kind != "speaker":
            continue
        limits[reference.line] = max(
            limits.get(reference.line, 0), reference.end_character
        )
    return limits


def _screen_local_variables(analysis: Analysis) -> list[tuple[str, int, int]]:
    """Screen ``default`` names together with the screen's line range."""
    result: list[tuple[str, int, int]] = []
    for block in analysis.blocks:
        if block.line.first_word != "screen":
            continue
        start = block.line.start_line
        end = block.end_line
        for item in analysis.lines:
            if item.kind != "code" or item.start_line < start or item.end_line > end:
                continue
            match = _SCREEN_VARIABLE.match(item.text)
            if match is not None:
                result.append((match.group(1), start, end))
    return result


def _syntax_skip_spans(
    analysis: Analysis, raw_lines: list[str]
) -> set[tuple[int, int]]:
    """Token positions that are Ren'Py syntax rather than variable uses."""
    skip: set[tuple[int, int]] = set()
    for item in analysis.lines:
        if item.kind != "code" or item.start_line >= len(raw_lines):
            continue
        raw = raw_lines[item.start_line]
        tokens = _line_tokens(raw)
        if not tokens:
            continue
        line = item.start_line
        words = _enclosing_words(analysis, line)
        in_python = "python" in words
        in_screen = "screen" in words
        in_language = bool(words & _LANGUAGE_WORDS)
        first_column, first = tokens[0]
        starts_with_code = raw.lstrip().startswith("$")

        if in_screen and not in_python and not starts_with_code:
            skip.add((line, first_column))
            if first in {"default", "define", "for"} and len(tokens) > 1:
                skip.add((line, tokens[1][0]))
        elif in_language and not in_python:
            skip.add((line, first_column))
            if (
                "layeredimage" in words
                and first in {"attribute", "group", "variant"}
                and len(tokens) > 1
            ):
                skip.add((line, tokens[1][0]))
        elif not in_python and first in _STATEMENT_WORDS:
            skip.add((line, first_column))

        if in_python:
            continue
        _skip_clauses(tokens, skip, line)
        if first in {"play", "queue", "stop"}:
            if len(tokens) > 1:
                skip.add((line, tokens[1][0]))
            for column, token in tokens[1:]:
                if token in _AUDIO_WORDS:
                    skip.add((line, column))
    return skip


def _skip_clauses(
    tokens: list[tuple[int, str]], skip: set[tuple[int, int]], line: int
) -> None:
    for position, (column, token) in enumerate(tokens):
        if token not in _CLAUSE_WORDS:
            continue
        skip.add((line, column))
        if position + 1 >= len(tokens):
            continue
        if token == "behind":
            for next_column, next_token in tokens[position + 1 :]:
                if next_token in _CLAUSE_WORDS:
                    break
                skip.add((line, next_column))
        elif token in {"as", "onlayer", "with"}:
            skip.add((line, tokens[position + 1][0]))


def _enclosing_words(analysis: Analysis, line: int) -> set[str]:
    words: set[str] = set()
    block = analysis.block_at(line)
    while block is not None:
        words.add(block.line.first_word)
        if "python" in block.line.text.split("#", 1)[0]:
            words.add("python")
        block = block.parent
    return words


def _line_tokens(raw: str) -> list[tuple[int, str]]:
    return [
        (utf16_length(raw[: match.start()]), match.group(0))
        for match in _TOKEN.finditer(raw)
    ]


def _interpolation_spans(
    source: str, start: int, end: int, line: int, line_start: int
) -> list[_VariableSpan]:
    result: list[_VariableSpan] = []
    for match in _INTERPOLATION_TOKEN.finditer(source, start, end):
        previous = _previous_significant(source, match.start())
        if previous == "." or _keyword_argument(source, match.end(), previous):
            continue
        column = utf16_length(source[line_start : match.start()])
        result.append(
            _VariableSpan(
                line,
                column,
                column + utf16_length(match.group(0)),
                match.group(0),
                quoted=True,
            )
        )
    return result


def _previous_significant(source: str, index: int) -> str:
    index -= 1
    while index >= 0 and source[index] in " \t":
        index -= 1
    return source[index] if index >= 0 else ""


def _keyword_argument(source: str, index: int, previous: str) -> bool:
    while index < len(source) and source[index] in " \t":
        index += 1
    if index >= len(source) or source[index] != "=":
        return False
    if index + 1 < len(source) and source[index + 1] == "=":
        return False
    return previous in {"(", ","}
