"""Formatter for Ren'Py scripts.

Most rules are whitespace-only, so they cannot change what a script does; quote
normalization changes delimiters only and leaves string values untouched:

* indentation is normalised to ``indent`` spaces per level (tabs expanded);
* trailing whitespace is removed;
* runs of blank lines are capped at ``max_blank_lines``;
* top-level ``label`` / ``screen`` / ``init`` / ``transform`` blocks are
  separated from the previous statement by a blank line (a comment block
  directly above them stays attached to them);
* the file ends with exactly one newline; the original line-ending style
  (LF or CRLF) is kept;
* the ``=`` of consecutive assignment lines at the same indentation level is
  aligned into one column;
* spacing around assignment and comparison operators is normalized in
  Python-ish statements such as ``$ points=1`` and ``define x=1``;
* keyword arguments and default parameter values inside brackets lose the
  spaces around ``=``, so ``color = "#fff"`` becomes ``color="#fff"``;
* single-quoted literals are rewritten to double quotes when the value cannot
  change (a literal containing an unescaped double quote is left alone);
* lines inside ``python:`` blocks also get arithmetic and bitwise operator
  spacing.

Never touched: the inside of strings, comments, slices and unary operators, and
(apart from a uniform shift) continuation lines of brackets or backslashes.
"""

import re
from dataclasses import dataclass

from .analysis import analyze
from .python_format import format_python_blocks
from .quotes import normalize_quotes
from .scanner import LineInfo, State, scan_line
from .spacing import normalize_python_spacing, normalize_statement_spacing

#: Top-level statements that get a blank line before them.
BLOCK_KEYWORDS = frozenset({"label", "screen", "init", "transform"})

_TAB = 4  # tab stop used to *measure* existing indentation

#: A neighbouring ``=`` that turns it into a comparison or augmented
#: assignment (``==``, ``!=``, ``<=``, ``+=``, ``:=`` ...).
_EQ_BLOCKERS = frozenset("=!<>+-*/%&|^~@:")

#: A Python block whose body should get full Python operator spacing.
_PYTHON_BLOCK = re.compile(r"^(?:init\s+)?python(?:\s+early)?(?:\s+in\s+[\w.]+)?\s*:")


@dataclass(frozen=True)
class FormatOptions:
    indent: int = 4
    max_blank_lines: int = 2
    align_equals: bool = True
    normalize_spacing: bool = True
    normalize_quotes: bool = True
    format_python: bool = False


@dataclass
class _Entry:
    text: str
    kind: str  # "code" | "comment" | "blank" | "verbatim"
    depth: int = 0


def _leading_width(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(line[: len(line) - len(stripped)].expandtabs(_TAB))


def _first_word(text: str) -> str:
    word = text.split(None, 1)[0] if text else ""
    return word.rstrip(":")


def format_source(source: str, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    eol = "\r\n" if "\r\n" in source else "\n"
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        _ = lines.pop()

    out: list[_Entry] = []
    stack = [0]  # original indentation of each open block
    expect_indent = False  # previous code line opened a block (ends with ':')
    delta = 0  # new indent - old indent of the current logical line
    state = State()
    python_lines: set[int] = (
        _python_block_lines(text, options) if options.normalize_spacing else set()
    )

    for index, raw in enumerate(lines):
        info: LineInfo = scan_line(raw, state)
        ends_clean_of_string = info.end.quote is None

        if not info.start.clean:
            # Continuation of a logical line.
            if info.start.quote is not None:
                # Inside a string: keep verbatim (only drop trailing blanks
                # once the string has closed on this line).
                text_out = raw.rstrip() if ends_clean_of_string else raw
            elif raw.strip() == "":
                text_out = ""
            else:
                width = max(0, _leading_width(raw) + delta)
                body = raw.lstrip(" \t")
                body = body.rstrip() if ends_clean_of_string else body
                if options.normalize_spacing and index in python_lines:
                    body = normalize_python_spacing(body)
                text_out = " " * width + body
            out.append(_Entry(text_out, "verbatim"))
            state = info.end
            continue

        stripped = raw.strip()
        if stripped == "":
            out.append(_Entry("", "blank"))
            state = info.end
            continue

        orig = _leading_width(raw)
        body = raw.lstrip(" \t")
        body = body.rstrip() if ends_clean_of_string else body

        if stripped.startswith("#"):
            k = max(i for i, v in enumerate(stack) if v <= orig)
            depth = k
            if k == len(stack) - 1 and orig > stack[-1] and expect_indent:
                depth = len(stack)  # first comment inside a block that is about to open
            kind = "comment"
        else:
            while len(stack) > 1 and orig < stack[-1]:
                _ = stack.pop()
            if orig > stack[-1]:
                stack.append(orig)
            depth = len(stack) - 1
            expect_indent = info.last_char == ":"
            kind = "code"

            if depth == 0 and _first_word(stripped) in BLOCK_KEYWORDS:
                _ensure_blank_before(out)
            if options.normalize_spacing:
                body = (
                    normalize_python_spacing(body)
                    if index in python_lines
                    else normalize_statement_spacing(body)
                )

        new_indent = options.indent * depth
        delta = new_indent - orig
        out.append(_Entry(" " * new_indent + body, kind, depth))
        state = info.end

    result = _render(out, options, eol)
    if options.format_python:
        result = format_python_blocks(result)
    if options.normalize_quotes:
        result = normalize_quotes(result)
    return result


def _python_block_lines(source: str, options: FormatOptions) -> set[int]:
    """Physical line numbers that are inside a ``python:`` block body."""
    analysis = analyze(source, default_indent=options.indent)
    result: set[int] = set()
    for block in analysis.blocks:
        if _PYTHON_BLOCK.match(block.line.text):
            result.update(range(block.line.start_line + 1, block.end_line + 1))
    return result


def _ensure_blank_before(out: list[_Entry]) -> None:
    j = len(out)
    while j > 0 and out[j - 1].kind == "comment" and out[j - 1].depth == 0:
        j -= 1
    if j > 0 and out[j - 1].kind != "blank":
        out.insert(j, _Entry("", "blank"))


def _assignment_equals(text: str) -> int | None:
    """Index of the top-level assignment ``=`` in *text*, if there is one.

    ``=`` inside strings, comments or brackets (keyword arguments in a call,
    for example) is ignored, as are ``==``, ``!=``, ``+=`` and friends.
    """
    quote: str | None = None
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
            elif text.startswith(quote, i):
                i += len(quote)
                quote = None
            else:
                i += 1
            continue
        if ch == "#":
            break
        if ch in "\"'":
            quote = ch * 3 if text.startswith(ch * 3, i) else ch
            i += len(quote)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "=" and depth == 0:
            prev = text[i - 1] if i else ""
            nxt = text[i + 1] if i + 1 < n else ""
            if (
                prev not in _EQ_BLOCKERS
                and nxt != "="
                # Both sides must contain something, otherwise this is not a
                # real assignment (and there is nothing to align).
                and text[:i].strip()
                and text[i + 1 :].strip()
            ):
                return i
        i += 1
    return None


def _align_equals(entries: list[_Entry]) -> None:
    """Pad consecutive assignments so their ``=`` line up."""
    i = 0
    while i < len(entries):
        first = entries[i]
        eq = _assignment_equals(first.text) if first.kind == "code" else None
        if eq is None:
            i += 1
            continue

        group: list[tuple[int, int]] = [(i, eq)]
        j = i + 1
        while j < len(entries):
            nxt = entries[j]
            if nxt.kind != "code" or nxt.depth != first.depth:
                break
            nxt_eq = _assignment_equals(nxt.text)
            if nxt_eq is None:
                break
            group.append((j, nxt_eq))
            j += 1

        if len(group) > 1:
            parts: list[tuple[int, str, str]] = []
            for k, pos in group:
                text = entries[k].text
                parts.append((k, text[:pos].rstrip(), text[pos + 1 :].lstrip()))
            width = max(len(left) for _, left, _ in parts)
            for k, left, right in parts:
                entries[k] = _Entry(
                    left + " " * (width - len(left) + 1) + "= " + right,
                    entries[k].kind,
                    entries[k].depth,
                )
        i = j


def _render(out: list[_Entry], options: FormatOptions, eol: str) -> str:
    kept: list[_Entry] = []
    blanks = 0
    for entry in out:
        if entry.kind == "blank":
            if not kept:  # no leading blank lines
                continue
            blanks += 1
            if blanks > options.max_blank_lines:
                continue
        else:
            blanks = 0
        kept.append(entry)
    # Only formatter-made blanks are dropped at the end; "verbatim" entries
    # (e.g. an empty line inside an unterminated string) stay.
    while kept and kept[-1].kind == "blank":
        _ = kept.pop()
    if not kept:
        return ""
    if options.align_equals:
        _align_equals(kept)
    return eol.join(e.text for e in kept) + eol
