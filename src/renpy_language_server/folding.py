"""Indentation-aware folding ranges for Ren'Py scripts.

Zed falls back to indentation-based folding when a language server does not
provide folding ranges. That heuristic can attach a menu choice's fold to the
next choice. This module reports explicit block ranges instead.

A logical line can span several physical lines (open brackets, backslash
continuations, multi-line strings). Fold ranges always cover whole physical
lines and never end on a trailing blank line.
"""

from dataclasses import dataclass

from .scanner import State, scan_line

_TAB = 4


@dataclass(frozen=True)
class FoldRange:
    start_line: int
    end_line: int


@dataclass
class _LogicalLine:
    start_line: int
    end_line: int
    indent: int
    last_char: str
    is_comment: bool


@dataclass
class _OpenBlock:
    indent: int
    start_line: int
    last_end_line: int | None = None


def folding_ranges(source: str) -> list[FoldRange]:
    """Return explicit fold ranges for every colon-terminated Ren'Py block."""
    logical = _logical_lines(source)
    stack: list[_OpenBlock] = []
    ranges: list[FoldRange] = []

    for line in logical:
        while stack and line.indent <= stack[-1].indent:
            _close_block(stack.pop(), ranges)

        for block in stack:
            block.last_end_line = line.end_line

        if line.last_char == ":" and not line.is_comment:
            stack.append(_OpenBlock(line.indent, line.start_line))

    while stack:
        _close_block(stack.pop(), ranges)

    ranges.sort(key=lambda item: (item.start_line, item.end_line))
    return ranges


def _close_block(block: _OpenBlock, ranges: list[FoldRange]) -> None:
    if block.last_end_line is None or block.last_end_line <= block.start_line:
        return
    ranges.append(FoldRange(block.start_line, block.last_end_line))


def _logical_lines(source: str) -> list[_LogicalLine]:
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    state = State()
    logical: list[_LogicalLine] = []
    current: _LogicalLine | None = None

    for index, raw in enumerate(lines):
        info = scan_line(raw, state)
        stripped = raw.strip()

        if info.start.clean:
            if current is not None:
                logical.append(current)
                current = None
            if stripped:
                current = _LogicalLine(
                    start_line=index,
                    end_line=index,
                    indent=_leading_width(raw),
                    last_char=info.last_char,
                    is_comment=stripped.startswith("#"),
                )
        elif current is not None:
            current.end_line = index
            if info.last_char:
                current.last_char = info.last_char

        state = info.end

    if current is not None:
        logical.append(current)
    return logical


def _leading_width(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(line[: len(line) - len(stripped)].expandtabs(_TAB))
