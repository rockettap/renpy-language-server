"""Per-document and workspace symbol index.

The index is intentionally a light, line-based parser. It only records the
declarations that the editor needs for navigation, diagnostics and completion;
it never executes Ren'Py code and never needs a full syntax tree. Python blocks
are handled by a small indentation parser in :mod:`renpy_language_server.python_index`.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pygls.uris import to_fs_path

from .analysis import Analysis, analyze
from .python_index import PythonIndex, parse_python
from .python_index import enclosing_python_class as python_class_at
from .targets import find_target

SymbolKind = Literal[
    "label",
    "screen",
    "transform",
    "image",
    "character",
    "style",
    "layeredimage",
    "variable",
    "class",
    "callable",
    "method",
    "field",
    "property",
    "store",
    "persistent",
    "testcase",
    "translation",
]
ReferenceKind = Literal[
    "jump",
    "call",
    "image",
    "screen",
    "transform",
    "speaker",
    "use",
    "style",
    "member",
    "class",
    "persistent",
    "store",
]

SOURCE_SUFFIXES = frozenset({".rpy", ".rpym"})
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "cache",
        "saves",
        "dist",
        "build",
    }
)
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 20_000
MAX_MEMBER_REFERENCES = 5_000
_EXTENDED_KINDS = frozenset({"store", "persistent", "testcase", "translation"})

_LABEL_RE = re.compile(r"^label\s+([A-Za-z_.][\w.]*)\s*(?:\(|:)")
_SCREEN_RE = re.compile(r"^screen\s+([A-Za-z_]\w*)\s*(?:\(|:)")
_TRANSFORM_RE = re.compile(r"^transform\s+([A-Za-z_]\w*)\s*(?:\(|:)")
_IMAGE_RE = re.compile(r"^image\s+([^=\n:]+?)\s*(?:=|:)")
_STYLE_RE = re.compile(r"^style\s+([A-Za-z_]\w*)\b")
_LAYEREDIMAGE_RE = re.compile(r"^layeredimage\s+([^:\n]+?)\s*:")
_CHARACTER_RE = re.compile(
    r"^(?:define|default)(?:\s+[-+]?\d+)?\s+([A-Za-z_]\w*)\s*=\s*"
    r"(?:Character|DynamicCharacter)\s*\(\s*(?:\"([^\"]*)\"|'([^']*)')?"
)
_VARIABLE_RE = re.compile(
    r"^(define|default)(?:\s+[-+]?\d+)?\s+([A-Za-z_]\w*)\s*(?:[+]|\|)?="
)
_PERSISTENT_RE = re.compile(
    r"^(define|default)(?:\s+[-+]?\d+)?\s+persistent\.([A-Za-z_]\w*)"
    r"\s*(?:[+]|\|)?="
)
_STORE_RE = re.compile(
    r"^(?:init(?:\s+[-+]?\d+)?\s+)?python(?:\s+early)?\s+in\s+"
    r"([A-Za-z_]\w*)\s*:"
)
_TESTCASE_RE = re.compile(r"^testcase\s+([A-Za-z_]\w*)\s*:")
_TRANSLATION_RE = re.compile(r"^translate\s+([A-Za-z_]\w*)\s+([A-Za-z_][\w.]*)\s*:")


@dataclass(frozen=True)
class IndexOptions:
    """Options that control which declaration families are indexed."""

    extended: bool = True
    members: bool = True


@dataclass(frozen=True)
class Symbol:
    """One indexed declaration."""

    name: str
    kind: SymbolKind
    uri: str
    line: int
    character: int
    end_line: int
    detail: str = ""
    source_name: str = ""
    parameters: str = ""
    container: str = ""


@dataclass(frozen=True)
class Reference:
    """One indexed use of a name."""

    name: str
    kind: ReferenceKind
    uri: str
    line: int
    character: int
    end_character: int
    source_name: str = ""
    container: str = ""


@dataclass(frozen=True)
class DocumentIndex:
    """Symbols, references and source text parsed from one file."""

    uri: str
    version: int | None
    symbols: tuple[Symbol, ...]
    references: tuple[Reference, ...] = ()
    source: str = ""
    analysis: Analysis | None = None
    options: IndexOptions = IndexOptions()


class WorkspaceIndex:
    """A mutable map of URI to :class:`DocumentIndex`."""

    def __init__(self, options: IndexOptions | None = None) -> None:
        self.options = options or IndexOptions()
        self._documents: dict[str, DocumentIndex] = {}

    def update(self, uri: str, source: str, version: int | None = None) -> None:
        existing = self._documents.get(uri)
        if existing is not None and version is not None and existing.version == version:
            return
        self._documents[uri] = parse_document(uri, source, version, self.options)

    def remove(self, uri: str) -> None:
        self._documents.pop(uri, None)

    def get(self, uri: str) -> DocumentIndex | None:
        return self._documents.get(uri)

    def merge(self, documents: Iterable[DocumentIndex]) -> None:
        for document in documents:
            self._documents[document.uri] = document

    def clear(self) -> None:
        self._documents.clear()

    def uris(self) -> list[str]:
        return list(self._documents)

    def all_symbols(self) -> list[Symbol]:
        return [symbol for doc in self._documents.values() for symbol in doc.symbols]

    def by_kind(self, kind: SymbolKind) -> list[Symbol]:
        return [symbol for symbol in self.all_symbols() if symbol.kind == kind]

    def find(self, kind: SymbolKind, name: str) -> list[Symbol]:
        return [
            symbol
            for symbol in self.all_symbols()
            if symbol.kind == kind and symbol.name == name
        ]

    def labels(self) -> dict[str, list[Symbol]]:
        result: dict[str, list[Symbol]] = {}
        for symbol in self.by_kind("label"):
            result.setdefault(symbol.name, []).append(symbol)
        return result

    def all_references(self) -> list[Reference]:
        return [ref for doc in self._documents.values() for ref in doc.references]

    def references(self, kind: ReferenceKind, name: str) -> list[Reference]:
        return [
            ref
            for ref in self.all_references()
            if ref.kind == kind and ref.name == name
        ]


def parse_document(
    uri: str,
    source: str,
    version: int | None = None,
    options: IndexOptions | None = None,
) -> DocumentIndex:
    """Parse a single file into symbols and references."""
    settings = options or IndexOptions()
    analysis = analyze(source)
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    symbols: list[Symbol] = []
    references: list[Reference] = []
    current_global: str | None = None
    python = (
        parse_python(analysis, raw_lines, len(source))
        if settings.extended
        else PythonIndex()
    )

    for line in analysis.lines:
        if line.kind != "code":
            continue

        parsed = _parse_line(line.text)
        if (
            parsed is not None
            and not settings.extended
            and parsed[0] in _EXTENDED_KINDS
        ):
            parsed = None
        if (
            parsed is not None
            and parsed[0] == "variable"
            and _in_screen(analysis, line.start_line)
        ):
            parsed = None
        if parsed is not None:
            kind, name, detail, parameters, container = parsed
            source_name = name
            if kind == "label":
                name, current_global = _qualified_label(name, current_global)

            raw = raw_lines[line.start_line] if line.start_line < len(raw_lines) else ""
            character = _column_of(raw, source_name, kind, container)
            end_line = _symbol_end_line(analysis, line.start_line, line.end_line)
            symbols.append(
                Symbol(
                    name=name,
                    kind=kind,
                    uri=uri,
                    line=line.start_line,
                    character=character,
                    end_line=end_line,
                    detail=detail,
                    source_name=source_name,
                    parameters=parameters,
                    container=container,
                )
            )

        if line.start_line < len(raw_lines):
            references.extend(
                _parse_references(
                    uri,
                    line.text,
                    raw_lines[line.start_line],
                    line.start_line,
                    current_global,
                    _speaker_context(analysis, line.start_line),
                )
            )
            if settings.extended:
                references.extend(
                    _parse_code_references(
                        uri,
                        raw_lines[line.start_line],
                        line.start_line,
                        python.class_at.get(line.start_line, ""),
                        python.classes,
                        python.stores,
                        settings.members,
                    )
                )

    for item in python.symbols:
        raw = raw_lines[item.line] if item.line < len(raw_lines) else ""
        symbols.append(
            Symbol(
                name=item.name,
                kind=item.kind,
                uri=uri,
                line=item.line,
                character=_column_of(raw, item.name, item.kind, item.container),
                end_line=_symbol_end_line(analysis, item.line, item.line),
                detail=item.detail,
                source_name=item.name,
                parameters=item.parameters,
                container=item.container,
            )
        )

    for base in python.bases:
        references.append(
            Reference(
                name=base.name,
                kind="class",
                uri=uri,
                line=base.line,
                character=base.character,
                end_character=base.character + utf16_length(base.name),
            )
        )

    symbols.sort(key=lambda item: (item.line, item.character))
    references.sort(key=lambda item: (item.line, item.character))
    return DocumentIndex(
        uri=uri,
        version=version,
        symbols=tuple(symbols),
        references=tuple(references),
        source=source,
        analysis=analysis,
        options=settings,
    )


def _qualified_label(name: str, current_global: str | None) -> tuple[str, str | None]:
    """Return a label's full name and the global label context after it."""
    if name.startswith("."):
        if current_global is None:
            return name, None
        return f"{current_global}{name}", current_global
    if "." in name:
        return name, name.split(".", 1)[0]
    return name, name


def global_label_at(source: str, line: int) -> str | None:
    """Global label that local labels after ``line`` belong to."""
    contexts = global_label_contexts(source)
    if 0 <= line < len(contexts):
        return contexts[line]
    return None


def global_label_contexts(source: str) -> list[str | None]:
    """Global label in effect at each physical line of ``source``."""
    return label_contexts(analyze(source))


def label_contexts(analysis: Analysis) -> list[str | None]:
    """Global label in effect at each physical line of an analysis."""
    contexts: list[str | None] = []
    current: str | None = None
    for item in analysis.lines:
        if item.kind == "code":
            parsed = _parse_line(item.text)
            if parsed is not None and parsed[0] == "label":
                name = parsed[1]
                if not name.startswith("."):
                    current = name.split(".", 1)[0]
        contexts.extend([current] * (item.end_line - item.start_line + 1))
    return contexts


def enclosing_python_class(source: str, line: int) -> str | None:
    """Innermost Python class body containing physical ``line``."""
    return python_class_at(analyze(source), line)


def resolve_label_name(source: str, line: int, target: str) -> str | None:
    """Resolve a ``.local`` target to the full ``global.local`` name."""
    if not target.startswith("."):
        return target
    return qualified_local_name(target, global_label_at(source, line))


def qualified_local_name(target: str, context: str | None) -> str | None:
    """Combine a known global label context with a written target name."""
    if not target.startswith("."):
        return target
    return f"{context}{target}" if context is not None else None


def _parse_line(text: str) -> tuple[SymbolKind, str, str, str, str] | None:
    match = _LABEL_RE.match(text)
    if match is not None:
        return "label", match.group(1), "label", _parameters(text), ""

    match = _SCREEN_RE.match(text)
    if match is not None:
        return "screen", match.group(1), "screen", _parameters(text), ""

    match = _TRANSFORM_RE.match(text)
    if match is not None:
        return "transform", match.group(1), "transform", _parameters(text), ""

    match = _IMAGE_RE.match(text)
    if match is not None:
        name = match.group(1).strip()
        if name:
            return "image", name, "image", "", ""

    match = _STYLE_RE.match(text)
    if match is not None:
        return "style", match.group(1), "style", "", ""

    match = _LAYEREDIMAGE_RE.match(text)
    if match is not None:
        name = match.group(1).strip()
        if name:
            return "layeredimage", name, "layeredimage", "", ""

    match = _STORE_RE.match(text)
    if match is not None:
        return "store", match.group(1), "store", "", ""

    match = _TESTCASE_RE.match(text)
    if match is not None:
        return "testcase", match.group(1), "testcase", "", ""

    match = _TRANSLATION_RE.match(text)
    if match is not None:
        language = match.group(1)
        return "translation", match.group(2), f"translate {language}", "", language

    match = _PERSISTENT_RE.match(text)
    if match is not None:
        return "persistent", match.group(2), match.group(1), "", "persistent"

    match = _CHARACTER_RE.match(text)
    if match is not None:
        name = match.group(1)
        display = match.group(2) if match.group(2) is not None else match.group(3)
        detail = f'character "{display}"' if display else "character"
        return "character", name, detail, "", ""

    match = _VARIABLE_RE.match(text)
    if match is not None:
        return "variable", match.group(2), match.group(1), "", ""

    return None


def _parameters(text: str) -> str:
    """Return the contents of the first balanced parenthesis group."""
    start = text.find("(")
    if start < 0:
        return ""
    depth = 0
    quote: str | None = None
    i = start
    while i < len(text):
        char = text[i]
        if quote is not None:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
        i += 1
    return ""


_CLAUSE_WORDS = frozenset({"at", "with", "behind", "onlayer", "as", "zorder"})
_SCREEN_WORDS = frozenset({"show", "hide", "call"})


def _parse_references(
    uri: str,
    text: str,
    raw: str,
    line: int,
    current_global: str | None,
    allow_speaker: bool,
) -> list[Reference]:
    stripped = text.strip()
    if not stripped:
        return []
    words = stripped.split()
    first = words[0]

    target = find_target(raw)
    if target is not None:
        kind = "jump" if first == "jump" else "call"
        return [
            _reference(
                uri,
                kind,
                target.name,
                target.name,
                raw,
                target.start,
                target.end,
                line,
                current_global,
            )
        ]

    if first in _SCREEN_WORDS and len(words) >= 3 and words[1] == "screen":
        name = words[2].split("(", 1)[0]
        if name and name != "expression":
            hint = _token_start(raw, stripped, 2)
            return [_simple_reference(uri, "screen", name, raw, line, hint)]
        return []

    if first == "use" and len(words) >= 2 and words[1] != "expression":
        name = words[1].split("(", 1)[0]
        hint = _token_start(raw, stripped, 1)
        return [_simple_reference(uri, "use", name, raw, line, hint)]

    if first == "style" and "is" in words:
        index = words.index("is") + 1
        if index < len(words):
            name = words[index].split("(", 1)[0].rstrip(":,;")
            if name:
                hint = _token_start(raw, stripped, index)
                return [_simple_reference(uri, "style", name, raw, line, hint)]

    references: list[Reference] = []
    if first in {"show", "scene", "hide"}:
        image = _image_target(words)
        if image is not None:
            hint = _token_start(raw, stripped, 1)
            references.append(_simple_reference(uri, "image", image, raw, line, hint))
        references.extend(_at_targets(stripped, raw, line, uri))

    if allow_speaker:
        speaker = _speaker_target(stripped)
        if speaker is not None:
            hint = _token_start(raw, stripped, 0)
            references.append(
                _simple_reference(uri, "speaker", speaker, raw, line, hint)
            )
    return references


_ATTRIBUTE_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
_PERSISTENT_REF_RE = re.compile(r"(?<![\w.])persistent\.([A-Za-z_]\w*)")
_STORE_REF_RE = re.compile(r"(?<![\w.])store\.([A-Za-z_]\w*)")


def _parse_code_references(
    uri: str,
    raw: str,
    line: int,
    class_name: str,
    classes: frozenset[str],
    stores: frozenset[str],
    member_references: bool,
) -> list[Reference]:
    """Attribute, namespace and base-class references from one code line."""
    if not member_references:
        return []
    masked = _mask_code(raw)
    references: list[Reference] = []

    for match in _PERSISTENT_REF_RE.finditer(masked):
        references.append(
            _reference(
                uri,
                "persistent",
                match.group(1),
                match.group(1),
                raw,
                match.start(1),
                match.end(1),
                line,
                None,
                "persistent",
            )
        )

    for match in _STORE_REF_RE.finditer(masked):
        references.append(
            _reference(
                uri,
                "store",
                match.group(1),
                match.group(1),
                raw,
                match.start(1),
                match.end(1),
                line,
                None,
                "store",
            )
        )

    if not member_references or len(references) >= MAX_MEMBER_REFERENCES:
        return references

    for match in _ATTRIBUTE_RE.finditer(masked):
        container = match.group(1)
        name = match.group(2)
        if container in {"persistent", "store"}:
            continue
        if container == "self":
            if not class_name:
                continue
            owner = class_name
        elif container in classes or container in stores or container[:1].isupper():
            owner = container
        else:
            continue
        references.append(
            _reference(
                uri,
                "member",
                name,
                name,
                raw,
                match.start(2),
                match.end(2),
                line,
                None,
                owner,
            )
        )
        if len(references) >= MAX_MEMBER_REFERENCES:
            break
    return references


def _mask_code(raw: str) -> str:
    """Blank out strings and comments while preserving character offsets."""
    chars = list(raw)
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(raw):
        char = raw[index]
        if quote is not None:
            if escaped:
                escaped = False
                chars[index] = " "
                index += 1
                continue
            if char == "\\":
                escaped = True
                chars[index] = " "
                index += 1
                continue
            if raw.startswith(quote * 3, index):
                for offset in range(index, index + 3):
                    chars[offset] = " "
                index += 3
                quote = None
                continue
            if char == quote:
                quote = None
            chars[index] = " "
            index += 1
            continue
        if char == "#":
            for offset in range(index, len(chars)):
                chars[offset] = " "
            break
        if char in "\"'":
            triple = raw.startswith(char * 3, index)
            if triple:
                for offset in range(index, index + 3):
                    chars[offset] = " "
                quote = char
                index += 3
                continue
            quote = char
            chars[index] = " "
            index += 1
            continue
        index += 1
    return "".join(chars)


mask_code = _mask_code

_DIALOGUE_BLOCKS = frozenset({"label", "translate"})
_NON_DIALOGUE_BLOCKS = frozenset(
    {"screen", "style", "transform", "layeredimage", "python"}
)


def _speaker_context(analysis: Analysis, line: int) -> bool:
    """True when ``line`` is inside a label or translation block."""
    block = analysis.block_at(line)
    while block is not None:
        word = block.line.first_word
        if word in _DIALOGUE_BLOCKS:
            return True
        if word in _NON_DIALOGUE_BLOCKS:
            return False
        block = block.parent
    return False


def _in_screen(analysis: Analysis, line: int) -> bool:
    """True when ``line`` is inside a screen block."""
    block = analysis.block_at(line)
    while block is not None:
        if block.line.first_word == "screen":
            return True
        block = block.parent
    return False


_SPEAKER_RE = re.compile(r"^([A-Za-z_]\w*)(?:\s+[A-Za-z_]\w*)*\s+[\"']")
_SPEAKER_KEYWORDS = frozenset(
    {
        "add",
        "button",
        "call",
        "centered",
        "contain",
        "default",
        "define",
        "else",
        "elif",
        "extend",
        "for",
        "frame",
        "grid",
        "hide",
        "hbox",
        "if",
        "image",
        "imagebutton",
        "init",
        "input",
        "jump",
        "key",
        "label",
        "layeredimage",
        "menu",
        "nvl",
        "on",
        "pause",
        "play",
        "python",
        "queue",
        "return",
        "scene",
        "screen",
        "show",
        "side",
        "stop",
        "style",
        "text",
        "textbutton",
        "timer",
        "transform",
        "translate",
        "use",
        "vbox",
        "vcentered",
        "viewport",
        "voice",
        "while",
        "window",
        "with",
    }
)


def _speaker_target(stripped: str) -> str | None:
    """Return the character name on a dialogue line, if there is one."""
    match = _SPEAKER_RE.match(stripped)
    if match is None:
        return None
    name = match.group(1)
    if name in _SPEAKER_KEYWORDS:
        return None
    return name


def _image_target(words: list[str]) -> str | None:
    parts: list[str] = []
    for word in words[1:]:
        if word in _CLAUSE_WORDS:
            break
        if word.endswith(":"):
            parts.append(word[:-1])
            break
        parts.append(word)
    if not parts or parts[0] in {"expression", "screen"}:
        return None
    return " ".join(parts)


_TOKEN_RE = re.compile(r"\S+")


def _token_start(raw: str, stripped: str, index: int) -> int:
    """Character offset in ``raw`` where the ``index``-th token begins."""
    base = max(raw.find(stripped), 0)
    for position, match in enumerate(_TOKEN_RE.finditer(stripped)):
        if position == index:
            return base + match.start()
    return base


def _at_targets(stripped: str, raw: str, line: int, uri: str) -> list[Reference]:
    matches = list(_TOKEN_RE.finditer(stripped))
    words = [match.group(0) for match in matches]
    if "at" not in words:
        return []

    base = max(raw.find(stripped), 0)

    result: list[Reference] = []
    for match, word in zip(
        matches[words.index("at") + 1 :], words[words.index("at") + 1 :]
    ):
        if word in _CLAUSE_WORDS:
            break
        offset = base + match.start()
        cursor = 0
        for part in word.split(","):
            name = part.strip()
            if name:
                local = word.find(name, cursor)
                result.append(
                    _simple_reference(uri, "transform", name, raw, line, offset + local)
                )
                cursor = local + len(name)
    return result


def _simple_reference(
    uri: str,
    kind: ReferenceKind,
    name: str,
    raw: str,
    line: int,
    start_hint: int = 0,
) -> Reference:
    start = raw.find(name, start_hint)
    if start < 0:
        start = raw.find(name)
    if start < 0:
        start = len(raw)
    return _reference(uri, kind, name, name, raw, start, start + len(name), line, None)


def _reference(
    uri: str,
    kind: ReferenceKind,
    name: str,
    source_name: str,
    raw: str,
    start: int,
    end: int,
    line: int,
    current_global: str | None,
    container: str = "",
) -> Reference:
    resolved = name
    if kind in {"jump", "call"}:
        resolved = qualified_local_name(name, current_global) or name
    character = utf16_length(raw[:start])
    return Reference(
        name=resolved,
        kind=kind,
        uri=uri,
        line=line,
        character=character,
        end_character=character + utf16_length(raw[start:end]),
        source_name=source_name,
        container=container,
    )


def _symbol_end_line(analysis: Analysis, start_line: int, fallback: int) -> int:
    block = analysis.block_at(start_line)
    if block is not None and block.line.start_line == start_line:
        return block.end_line
    return fallback


def _column_of(raw: str, name: str, kind: SymbolKind, container: str = "") -> int:
    if kind in {"character", "variable"}:
        keyword = "default" if raw.lstrip().startswith("default") else "define"
    elif kind in {"class"}:
        keyword = "class"
    elif kind in {"callable", "method", "property"}:
        keyword = "def"
    elif kind == "field":
        keyword = ""
    elif kind == "store":
        keyword = " in "
    elif kind == "persistent":
        keyword = "persistent"
    elif kind == "testcase":
        keyword = "testcase"
    elif kind == "translation":
        keyword = container
    else:
        keyword = kind
    hint = raw.find(keyword) if keyword else 0
    index = raw.find(name, hint + len(keyword)) if hint >= 0 else raw.find(name)
    if index < 0:
        index = raw.find(name)
    if index < 0:
        return 0
    # LSP character offsets are UTF-16 code units, not Python code points.
    return len(raw[:index].encode("utf-16-le")) // 2


def display_name(symbol: Symbol) -> str:
    """Fully qualified name for display, keeping the written span separate."""
    if symbol.container:
        return f"{symbol.container}.{symbol.name}"
    return symbol.name


def utf16_length(text: str) -> int:
    """Length of ``text`` in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def scan_workspace(
    roots: Iterable[Path], options: IndexOptions | None = None
) -> list[DocumentIndex]:
    """Read every Ren'Py file under ``roots`` and parse it."""
    settings = options or IndexOptions()
    documents: list[DocumentIndex] = []
    seen: set[str] = set()

    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            continue

        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if len(documents) >= MAX_FILES:
                break
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if _skipped(relative):
                continue
            try:
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            uri = path.as_uri()
            if uri in seen:
                continue
            seen.add(uri)

            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            documents.append(parse_document(uri, source, options=settings))

    return documents


def workspace_paths(uri_strings: Iterable[str]) -> list[Path]:
    """Convert workspace-folder URIs to local paths, keeping existing folders."""
    paths: list[Path] = []
    seen: set[str] = set()
    for value in uri_strings:
        fs_path = to_fs_path(value)
        if fs_path is None:
            continue
        path = Path(fs_path)
        key = str(path)
        if key not in seen:
            seen.add(key)
            paths.append(path)
    return paths


def _skipped(relative: Path) -> bool:
    parts = relative.parts[:-1]
    return any(part in SKIP_DIRS or part.startswith(".") for part in parts)
