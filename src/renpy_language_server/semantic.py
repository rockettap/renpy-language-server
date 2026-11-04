"""Semantic tokens for Ren'Py declarations, references and built-ins.

The provider is deliberately conservative: the tree-sitter grammar remains the
primary highlighter, and these tokens only augment it when a client opts in.
"""

import re
from dataclasses import dataclass

from lsprotocol import types

from . import builtins as api
from .analysis import Analysis
from .diagnostics import OBSOLETE_API_NAMES
from .index import Symbol, mask_code, parse_document, utf16_length
from .strings import iter_string_spans

TOKEN_TYPES = (
    "class",
    "function",
    "variable",
    "parameter",
    "property",
    "keyword",
    "string",
    "number",
)
TOKEN_MODIFIERS = ("declaration", "definition", "defaultLibrary", "deprecated")
LEGEND = types.SemanticTokensLegend(
    token_types=list(TOKEN_TYPES),
    token_modifiers=list(TOKEN_MODIFIERS),
)

_TOKEN_TYPE_INDEX = {name: index for index, name in enumerate(TOKEN_TYPES)}
_MODIFIER_BITS = {name: 1 << index for index, name in enumerate(TOKEN_MODIFIERS)}

_DECLARATION_TYPES = {
    "label": "function",
    "screen": "class",
    "transform": "function",
    "image": "variable",
    "character": "variable",
    "style": "class",
    "layeredimage": "variable",
    "variable": "variable",
    "class": "class",
    "callable": "function",
    "method": "function",
    "field": "property",
    "property": "property",
    "store": "class",
    "persistent": "variable",
    "testcase": "function",
    "translation": "variable",
}
_DEFINITION_KINDS = frozenset({"class", "callable", "method", "field", "property"})
_REFERENCE_TYPES = {
    "jump": "function",
    "call": "function",
    "screen": "class",
    "use": "class",
    "transform": "function",
    "image": "variable",
    "speaker": "variable",
    "style": "class",
    "member": "property",
    "class": "class",
    "persistent": "variable",
    "store": "variable",
}

_RENPY_KEYWORDS = frozenset(
    [
        "add",
        "at",
        "behind",
        "call",
        "camera",
        "contains",
        "default",
        "define",
        "elif",
        "else",
        "expression",
        "for",
        "from",
        "hide",
        "if",
        "image",
        "init",
        "jump",
        "label",
        "layeredimage",
        "menu",
        "nvl",
        "on",
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
        "text",
        "testcase",
        "testsuite",
        "transform",
        "translate",
        "use",
        "voice",
        "while",
        "window",
        "with",
        "zorder",
    ]
)
_PYTHON_KEYWORDS = frozenset(
    [
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "False",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "None",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "True",
        "try",
        "while",
        "with",
        "yield",
    ]
)
_KEYWORDS = _RENPY_KEYWORDS | _PYTHON_KEYWORDS
_WORD_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_NUMBER_RE = re.compile(r"(?<![\w.])(?:\d+(?:\.\d*)?|\.\d+)(?![\w.])")
_PARAMETER_SPLIT_RE = re.compile(r",(?![^()\[\]{}]*[)\]}])")
_PARAMETER_NAME_RE = re.compile(r"\s*\*{0,2}\s*([A-Za-z_]\w*)")


@dataclass(frozen=True)
class _Candidate:
    line: int
    start: int
    length: int
    token_type: str
    modifiers: tuple[str, ...]
    priority: int

    @property
    def end(self) -> int:
        return self.start + self.length


def semantic_tokens(
    uri: str,
    source: str,
    *,
    enabled: bool = True,
) -> types.SemanticTokens:
    """Return semantic tokens for one document, or an empty stream."""
    if not enabled:
        return types.SemanticTokens(data=[])

    document = parse_document(uri, source)
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    candidates: list[_Candidate] = []

    for symbol in document.symbols:
        _add_symbol(candidates, raw_lines, symbol)
        _add_parameters(candidates, raw_lines, symbol)

    for reference in document.references:
        text = reference.source_name or reference.name
        _add_utf16(
            candidates,
            reference.line,
            reference.character,
            text,
            _REFERENCE_TYPES.get(reference.kind, "variable"),
            (),
            1,
        )

    for index, raw in enumerate(raw_lines):
        masked = mask_code(raw)
        _add_builtins(candidates, raw_lines, masked, index)
        if document.analysis is not None:
            _add_keywords(candidates, raw_lines, index, document.analysis)
        _add_numbers(candidates, raw_lines, masked, index)

    for line, span in iter_string_spans(source):
        _add(
            candidates,
            raw_lines,
            line,
            span.start,
            raw_lines[line][span.start : span.end],
            "string",
            (),
            4,
        )

    selected = _select(candidates)
    return types.SemanticTokens(data=_encode(selected))


def _add_symbol(
    candidates: list[_Candidate], raw_lines: list[str], symbol: Symbol
) -> None:
    name = symbol.source_name or symbol.name
    token_type = _DECLARATION_TYPES.get(symbol.kind, "variable")
    modifiers = (
        ("declaration", "definition")
        if symbol.kind in _DEFINITION_KINDS
        else ("declaration",)
    )
    _add(
        candidates,
        raw_lines,
        symbol.line,
        symbol.character,
        name,
        token_type,
        modifiers,
        0,
    )


def _add_parameters(
    candidates: list[_Candidate], raw_lines: list[str], symbol: Symbol
) -> None:
    if not symbol.parameters or "\n" in symbol.parameters:
        return
    if symbol.line < 0 or symbol.line >= len(raw_lines):
        return
    raw = raw_lines[symbol.line]
    open_index = raw.find("(", symbol.character)
    if open_index < 0:
        return

    search_from = open_index + 1
    masked = mask_code(symbol.parameters)
    for part in _PARAMETER_SPLIT_RE.split(masked):
        match = _PARAMETER_NAME_RE.match(part)
        if match is None:
            continue
        name = match.group(1)
        start = raw.find(name, search_from)
        if start < 0:
            continue
        search_from = start + len(name)
        _add(
            candidates,
            raw_lines,
            symbol.line,
            start,
            name,
            "parameter",
            ("declaration",),
            0,
        )


def _add_builtins(
    candidates: list[_Candidate],
    raw_lines: list[str],
    masked: str,
    line: int,
) -> None:
    for match in _WORD_RE.finditer(masked):
        name = match.group(0)
        builtin = api.lookup(name)
        if builtin is None:
            if name in OBSOLETE_API_NAMES:
                _add(
                    candidates,
                    raw_lines,
                    line,
                    match.start(),
                    name,
                    "function",
                    ("defaultLibrary", "deprecated"),
                    3,
                )
            continue
        modifiers = ["defaultLibrary"]
        if name in OBSOLETE_API_NAMES:
            modifiers.append("deprecated")
        if builtin.type == "Action":
            token_type = "function"
        elif builtin.kind == "class":
            token_type = "class"
        elif builtin.kind == "function":
            token_type = "function"
        else:
            token_type = "variable"
        _add(
            candidates,
            raw_lines,
            line,
            match.start(),
            name,
            token_type,
            tuple(modifiers),
            3,
        )


def _add_keywords(
    candidates: list[_Candidate],
    raw_lines: list[str],
    line: int,
    analysis: Analysis,
) -> None:
    for item in analysis.lines:
        if item.start_line != line:
            continue
        if item.kind != "code":
            return
        if item.first_word not in _KEYWORDS:
            return
        start = raw_lines[line].find(item.first_word)
        if start < 0:
            return
        _add(
            candidates,
            raw_lines,
            line,
            start,
            item.first_word,
            "keyword",
            (),
            2,
        )
        return


def _add_numbers(
    candidates: list[_Candidate],
    raw_lines: list[str],
    masked: str,
    line: int,
) -> None:
    for match in _NUMBER_RE.finditer(masked):
        _add(
            candidates,
            raw_lines,
            line,
            match.start(0),
            match.group(0),
            "number",
            (),
            4,
        )


def _add(
    candidates: list[_Candidate],
    raw_lines: list[str],
    line: int,
    start: int,
    text: str,
    token_type: str,
    modifiers: tuple[str, ...],
    priority: int,
) -> None:
    if not text or line < 0 or line >= len(raw_lines):
        return
    raw = raw_lines[line]
    if start < 0 or start + len(text) > len(raw):
        return
    _add_utf16(
        candidates,
        line,
        utf16_length(raw[:start]),
        text,
        token_type,
        modifiers,
        priority,
    )


def _add_utf16(
    candidates: list[_Candidate],
    line: int,
    start: int,
    text: str,
    token_type: str,
    modifiers: tuple[str, ...],
    priority: int,
) -> None:
    length = utf16_length(text)
    if length <= 0:
        return
    candidates.append(
        _Candidate(
            line=line,
            start=start,
            length=length,
            token_type=token_type,
            modifiers=modifiers,
            priority=priority,
        )
    )


def _select(candidates: list[_Candidate]) -> list[_Candidate]:
    by_line: dict[int, list[_Candidate]] = {}
    for candidate in candidates:
        by_line.setdefault(candidate.line, []).append(candidate)

    selected: list[_Candidate] = []
    for items in by_line.values():
        accepted: list[_Candidate] = []
        for candidate in sorted(
            items,
            key=lambda item: (item.priority, item.start, -item.length),
        ):
            if any(
                candidate.start < other.end and other.start < candidate.end
                for other in accepted
            ):
                continue
            accepted.append(candidate)
        selected.extend(sorted(accepted, key=lambda item: (item.line, item.start)))
    return sorted(selected, key=lambda item: (item.line, item.start))


def _encode(candidates: list[_Candidate]) -> list[int]:
    data: list[int] = []
    previous_line = 0
    previous_start = 0
    for index, candidate in enumerate(candidates):
        if index == 0:
            delta_line = candidate.line
            delta_start = candidate.start
        else:
            delta_line = candidate.line - previous_line
            delta_start = (
                candidate.start - previous_start if delta_line == 0 else candidate.start
            )
        data.extend(
            [
                delta_line,
                delta_start,
                candidate.length,
                _TOKEN_TYPE_INDEX[candidate.token_type],
                _modifier_mask(candidate.modifiers),
            ]
        )
        previous_line = candidate.line
        previous_start = candidate.start
    return data


def _modifier_mask(modifiers: tuple[str, ...]) -> int:
    mask = 0
    for modifier in modifiers:
        mask |= _MODIFIER_BITS.get(modifier, 0)
    return mask
