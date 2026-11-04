"""Conservative indexing for declarations inside Ren'Py ``python:`` blocks.

The server does not execute or fully parse Python. This module only follows
indentation to recover the names that an editor needs: classes, functions,
methods, properties, fields and store boundaries. Anything ambiguous is
ignored; malformed input must never raise.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from .analysis import Analysis, Block

MAX_PYTHON_SYMBOLS = 1_000
MAX_PYTHON_BYTES = 500_000

PythonKind = Literal["class", "callable", "method", "field", "property"]

_PYTHON_BLOCK = re.compile(
    r"^(?:init(?:\s+[-+]?\d+)?\s+)?python(?:\s+early)?"
    r"(?:\s+in\s+([A-Za-z_]\w*))?\s*:"
)
_CLASS = re.compile(r"^class\s+([A-Za-z_]\w*)\s*(?:\((.*)\))?\s*:")
_CLASS_NAME = re.compile(r"^class\s+([A-Za-z_]\w*)")
_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\((.*)\)\s*(?:->\s*[^:]+)?:")
_DECORATOR = re.compile(r"^@\s*([\w.]+)")
_FIELD = re.compile(r"^([A-Za-z_]\w*)\s*(?::\s*[^=]+)?(?:[+]|\|)?=(?!=)")
_SELF_FIELD = re.compile(r"^self\.([A-Za-z_]\w*)\s*(?::\s*[^=]+)?(?:[+]|\|)?=(?!=)")
_BASE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")

_FIELD_KEYWORDS = frozenset(
    {
        "assert",
        "async",
        "await",
        "break",
        "case",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "lambda",
        "match",
        "nonlocal",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
)
_PROPERTY_DECORATORS = frozenset({"property", "cached_property"})


def _no_class_at() -> dict[int, str]:
    return {}


@dataclass(frozen=True)
class PythonSymbol:
    """One declaration recovered from a Python block."""

    kind: PythonKind
    name: str
    container: str
    line: int
    detail: str
    parameters: str = ""


@dataclass(frozen=True)
class ClassReference:
    """A base-class name written in a class statement."""

    name: str
    line: int
    character: int


@dataclass(frozen=True)
class PythonIndex:
    """Python declarations and per-line class context for one document."""

    symbols: tuple[PythonSymbol, ...] = ()
    classes: frozenset[str] = frozenset()
    stores: frozenset[str] = frozenset()
    class_at: dict[int, str] = field(default_factory=_no_class_at)
    bases: tuple[ClassReference, ...] = ()
    truncated: bool = False


@dataclass
class _Context:
    indent: int
    kind: str
    name: str


class _Limit(Exception):
    """Internal signal that the per-file symbol cap was reached."""


def parse_python(
    analysis: Analysis,
    raw_lines: list[str],
    source_size: int = 0,
    max_symbols: int | None = None,
) -> PythonIndex:
    """Return declarations found inside Python blocks of ``analysis``."""
    limit = MAX_PYTHON_SYMBOLS if max_symbols is None else max_symbols
    if source_size > MAX_PYTHON_BYTES:
        return PythonIndex()

    symbols: list[PythonSymbol] = []
    classes: set[str] = set()
    stores: set[str] = set()
    class_at: dict[int, str] = {}
    bases: list[ClassReference] = []
    seen_fields: set[tuple[str, str]] = set()
    covered: set[int] = set()

    try:
        for start, end, store, base_indent in _python_ranges(analysis):
            if store:
                stores.add(store)
            stack = (
                [_Context(base_indent, "store", store)]
                if store
                else [_Context(base_indent, "root", "")]
            )
            decorators: list[tuple[int, str]] = []

            for item in analysis.lines:
                if item.start_line <= start or item.start_line > end:
                    continue
                if item.kind != "code" or item.start_line in covered:
                    continue
                covered.add(item.start_line)

                while stack and item.indent <= stack[-1].indent:
                    if stack[-1].kind == "root":
                        break
                    stack.pop()

                if decorators and decorators[-1][0] != item.indent:
                    decorators.clear()

                text = _logical_text(raw_lines, item.start_line, item.end_line)
                enclosing_class = _nearest(stack, "class")
                enclosing_store = _nearest(stack, "store")
                container = enclosing_class or enclosing_store
                class_at[item.start_line] = enclosing_class

                decorator = _DECORATOR.match(text)
                if decorator is not None:
                    decorators.append((item.indent, decorator.group(1)))
                    continue

                match = _CLASS.match(text)
                if match is not None:
                    name = match.group(1)
                    classes.add(name)
                    symbols.append(
                        PythonSymbol("class", name, container, item.start_line, "class")
                    )
                    _guard(symbols, limit)
                    _collect_bases(
                        bases,
                        match.group(2),
                        raw_lines[item.start_line]
                        if item.start_line < len(raw_lines)
                        else "",
                        item.start_line,
                        name,
                    )
                    stack.append(_Context(item.indent, "class", name))
                    decorators.clear()
                    continue

                match = _DEF.match(text)
                if match is not None:
                    name = match.group(1)
                    is_property = any(
                        decorator_name.rsplit(".", 1)[-1] in _PROPERTY_DECORATORS
                        for _, decorator_name in decorators
                    )
                    if is_property:
                        kind: PythonKind = "property"
                        detail = "property"
                    elif enclosing_class:
                        kind = "method"
                        detail = "method"
                    else:
                        kind = "callable"
                        detail = "function"
                    symbols.append(
                        PythonSymbol(
                            kind,
                            name,
                            container,
                            item.start_line,
                            detail,
                            match.group(2).strip(),
                        )
                    )
                    _guard(symbols, limit)
                    stack.append(_Context(item.indent, "def", name))
                    decorators.clear()
                    continue

                if stack and stack[-1].kind in {"class", "store"}:
                    match = _FIELD.match(text)
                    if match is not None:
                        name = match.group(1)
                        if name not in _FIELD_KEYWORDS and not name.startswith("__"):
                            owner = stack[-1].name
                            key = (owner, name)
                            if key not in seen_fields:
                                seen_fields.add(key)
                                symbols.append(
                                    PythonSymbol(
                                        "field",
                                        name,
                                        owner,
                                        item.start_line,
                                        "field",
                                    )
                                )
                                _guard(symbols, limit)
                        continue

                if enclosing_class:
                    match = _SELF_FIELD.match(text)
                    if match is not None:
                        name = match.group(1)
                        key = (enclosing_class, name)
                        if key not in seen_fields:
                            seen_fields.add(key)
                            symbols.append(
                                PythonSymbol(
                                    "field",
                                    name,
                                    enclosing_class,
                                    item.start_line,
                                    "field",
                                )
                            )
                            _guard(symbols, limit)
    except _Limit:
        return PythonIndex(
            symbols=tuple(symbols),
            classes=frozenset(classes),
            stores=frozenset(stores),
            class_at=class_at,
            bases=tuple(bases),
            truncated=True,
        )

    return PythonIndex(
        symbols=tuple(symbols),
        classes=frozenset(classes),
        stores=frozenset(stores),
        class_at=class_at,
        bases=tuple(bases),
    )


def enclosing_python_class(analysis: Analysis, line: int) -> str | None:
    """Name of the innermost class body containing physical ``line``."""
    block = analysis.block_at(line)
    while block is not None:
        if block.line.first_word == "class" and _inside_python(block):
            match = _CLASS_NAME.match(block.line.text)
            if match is not None:
                return match.group(1)
        block = block.parent
    return None


def _inside_python(block: Block) -> bool:
    """True when the block or one of its parents is a Python block."""
    item: Block | None = block
    while item is not None:
        if _PYTHON_BLOCK.match(item.line.text):
            return True
        item = item.parent
    return False


def _python_ranges(
    analysis: Analysis,
) -> list[tuple[int, int, str, int]]:
    """Return ``(start_line, end_line, store_name, base_indent)`` ranges."""
    ranges: list[tuple[int, int, str, int]] = []
    for item in analysis.lines:
        if item.kind != "code":
            continue
        match = _PYTHON_BLOCK.match(item.text)
        if match is None:
            continue
        block = analysis.block_at(item.start_line)
        end = item.end_line
        if block is not None and block.line.start_line == item.start_line:
            end = block.end_line
        ranges.append((item.start_line, end, match.group(1) or "", item.indent))
    return ranges


def _logical_text(raw_lines: list[str], start: int, end: int) -> str:
    if start >= len(raw_lines):
        return ""
    last = min(end, len(raw_lines) - 1)
    return " ".join(part.strip() for part in raw_lines[start : last + 1]).strip()


def _nearest(stack: list[_Context], kind: str) -> str:
    for context in reversed(stack):
        if context.kind == kind:
            return context.name
    return ""


def _guard(symbols: list[PythonSymbol], limit: int) -> None:
    if len(symbols) >= limit:
        raise _Limit


def _collect_bases(
    result: list[ClassReference],
    raw_bases: str | None,
    raw: str,
    line: int,
    class_name: str,
) -> None:
    if not raw_bases:
        return
    search_from = raw.find(class_name) + len(class_name)
    for part in raw_bases.split(","):
        candidate = part.strip()
        if not candidate or "=" in candidate:
            continue
        match = _BASE.match(candidate)
        if match is None:
            continue
        name = match.group(0).rsplit(".", 1)[-1]
        if name in {"object", "metaclass"}:
            continue
        start = raw.find(match.group(0), search_from)
        if start < 0:
            start = raw.find(name, search_from)
        if start < 0:
            continue
        result.append(
            ClassReference(
                name=name,
                line=line,
                character=len(raw[:start].encode("utf-16-le")) // 2,
            )
        )
