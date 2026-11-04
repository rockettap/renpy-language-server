"""Logical lines and the block tree shared by server features.

The scanner already knows where a physical line continues an earlier logical
line. This module turns that information into two small structures:

* :class:`LogicalLine` - one Ren'Py statement, possibly spanning several
  physical lines;
* :class:`Block` - a colon-terminated statement with its indented body.

It is deliberately not a parser. It is accurate enough for symbols, navigation,
diagnostics and fold ranges, and it never treats the inside of a string or a
bracket continuation as a block opener.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from .scanner import State, scan_line

_TAB = 4
_FIRST_TOKEN = re.compile(r"\S+")

LineKind = Literal["code", "comment", "blank", "continuation"]


@dataclass(frozen=True)
class LogicalLine:
    """One Ren'Py statement, from its first to its last physical line."""

    text: str
    start_line: int
    end_line: int
    indent: int
    depth: int
    kind: LineKind
    first_word: str
    opens_block: bool


def _no_children() -> "list[Block]":
    return []


@dataclass
class Block:
    """A colon-terminated statement and its indented body."""

    line: LogicalLine
    parent: "Block | None"
    children: "list[Block]" = field(default_factory=_no_children)
    end_line: int = 0


@dataclass
class Analysis:
    """Result of analysing one source file."""

    lines: list[LogicalLine]
    blocks: list[Block]
    indent_unit: int

    def line_at(self, line: int) -> LogicalLine | None:
        """Return the logical line containing physical ``line``."""
        for item in self.lines:
            if item.start_line <= line <= item.end_line:
                return item
        return None

    def block_at(self, line: int) -> Block | None:
        """Return the innermost block whose range contains ``line``."""
        found: Block | None = None
        for block in self.blocks:
            if block.line.start_line <= line <= block.end_line and (
                found is None or block.line.start_line >= found.line.start_line
            ):
                found = block
        return found

    def enclosing_label(self, line: int) -> Block | None:
        """Return the closest ``label`` block containing ``line``."""
        block = self.block_at(line)
        while block is not None:
            if block.line.first_word == "label":
                return block
            block = block.parent
        return None


@dataclass
class _Pending:
    start_line: int
    end_line: int
    text: str
    indent: int
    kind: LineKind
    first_word: str
    last_char: str


def analyze(source: str, *, default_indent: int = 4) -> Analysis:
    """Analyse ``source`` into logical lines and a block tree."""
    raw_lines = _split_lines(source)
    pending = _collect_logical_lines(raw_lines)
    indent_unit = _infer_indent_unit(pending, default_indent)

    stack: list[Block] = []
    blocks: list[Block] = []
    lines: list[LogicalLine] = []

    for item in pending:
        if item.kind != "blank":
            while stack and item.indent <= stack[-1].line.indent:
                _close_block(stack.pop())

        line = LogicalLine(
            text=item.text,
            start_line=item.start_line,
            end_line=item.end_line,
            indent=item.indent,
            depth=len(stack),
            kind=item.kind,
            first_word=item.first_word,
            opens_block=item.kind != "comment" and item.last_char == ":",
        )
        lines.append(line)

        if item.kind != "blank":
            for block in stack:
                block.end_line = item.end_line

        if line.opens_block:
            parent = stack[-1] if stack else None
            block = Block(line=line, parent=parent, end_line=line.end_line)
            blocks.append(block)
            if parent is not None:
                parent.children.append(block)
            stack.append(block)

    while stack:
        _close_block(stack.pop())

    return Analysis(lines=lines, blocks=blocks, indent_unit=indent_unit)


def _close_block(block: Block) -> None:
    block.end_line = max(block.end_line, block.line.end_line)


def _split_lines(source: str) -> list[str]:
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


def _collect_logical_lines(raw_lines: list[str]) -> list[_Pending]:
    state = State()
    pending: list[_Pending] = []
    current: _Pending | None = None

    for index, raw in enumerate(raw_lines):
        info = scan_line(raw, state)
        stripped = raw.strip()

        if state.clean:
            if current is not None:
                pending.append(current)
                current = None

            if stripped:
                text = stripped
                current = _Pending(
                    start_line=index,
                    end_line=index,
                    text=text,
                    indent=_leading_width(raw),
                    kind="comment" if text.startswith("#") else "code",
                    first_word=_first_word(text),
                    last_char=info.last_char,
                )
            else:
                pending.append(
                    _Pending(
                        start_line=index,
                        end_line=index,
                        text="",
                        indent=0,
                        kind="blank",
                        first_word="",
                        last_char="",
                    )
                )
        elif current is not None:
            current.end_line = index
            if info.last_char:
                current.last_char = info.last_char
        else:
            # A continuation without a logical-line opener should not happen
            # with a balanced scanner. Keep it as a safe code line.
            current = _Pending(
                start_line=index,
                end_line=index,
                text=stripped,
                indent=_leading_width(raw),
                kind="continuation",
                first_word=_first_word(stripped),
                last_char=info.last_char,
            )

        state = info.end

    if current is not None:
        pending.append(current)
    return pending


def _infer_indent_unit(lines: list[_Pending], default_indent: int) -> int:
    for line in lines:
        if line.kind == "code" and line.indent > 0:
            return line.indent
    return default_indent if default_indent > 0 else _TAB


def _first_word(text: str) -> str:
    match = _FIRST_TOKEN.match(text)
    return match.group(0) if match else ""


def _leading_width(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(line[: len(line) - len(stripped)].expandtabs(_TAB))
