"""Physical-line scanner for Ren'Py source.

Ren'Py scripts are indentation based, but a *logical* line can span several
physical lines (open brackets, backslash continuation, multi-line strings).
The formatter must never touch the inside of those, so this module tracks the
lexical state across lines and reports, for every physical line, whether it
starts a new logical line.

It is deliberately not a parser: it only knows about strings, comments and
brackets, which is enough for whitespace-only formatting.

Assumption: a string opened with a single quote that is still open at the end
of a line continues on the next line (Ren'Py allows this); its content is left
untouched.
"""

from dataclasses import dataclass

_OPEN = "([{"
_CLOSE = ")]}"
_STRING_TOKEN = '"'  # stands in for "a complete string literal was seen"


@dataclass(frozen=True)
class State:
    """Lexical state at a line boundary."""

    quote: str | None = None  # '"', "'", '\"\"\"' or "'''" while inside a string
    depth: int = 0  # open brackets
    backslash: bool = False  # previous line ended with a continuation backslash

    @property
    def clean(self) -> bool:
        """True when the next physical line starts a logical line."""
        return self.quote is None and self.depth == 0 and not self.backslash


@dataclass(frozen=True)
class LineInfo:
    start: State  # state before the line
    end: State  # state after the line
    last_char: str  # last significant char outside strings/comments ('' if none)


def scan_line(line: str, state: State) -> LineInfo:
    quote = state.quote
    depth = state.depth
    last = ""
    in_comment = False
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]
        if quote is not None:
            if ch == "\\":
                i += 2  # skip the escaped character
            elif line.startswith(quote, i):
                i += len(quote)
                quote = None
                last = _STRING_TOKEN
            else:
                i += 1
            continue

        if ch == "#":
            in_comment = True
            break  # the rest of the line is a comment
        if ch in "\"'":
            quote = ch * 3 if line.startswith(ch * 3, i) else ch
            i += len(quote)
            continue
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        if not ch.isspace():
            last = ch
        i += 1

    backslash = quote is None and not in_comment and line.rstrip().endswith("\\")
    return LineInfo(
        start=state,
        end=State(quote=quote, depth=depth, backslash=backslash),
        last_char=last,
    )
