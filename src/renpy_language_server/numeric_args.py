"""Normalize numeric duration arguments in Ren'Py statements and ATL.

Ren'Py accepts both integers and floats for every documented duration
position.  This module rewrites *pure numeric literals* in those positions to
one spelling, so ``pause 1`` becomes ``pause 1.0`` (or ``pause (1.0)`` when the
parenthesised style is selected).

Only literals that are the whole argument are touched, optionally wrapped in
balanced outer parentheses.  Expressions such as ``pause delay + 1`` or
``timer cooldown`` are left alone, because changing their spelling could change
what they mean.  Non-duration numbers (counts, coordinates, sizes, volumes and
ATL property values) are never rewritten.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, cast

from .analysis import Analysis, LogicalLine

NumericStyle = Literal["bare", "parens"]

#: Statement families that have documented numeric duration positions.
NUMERIC_FAMILIES = frozenset({"pause", "atl", "timer", "audio", "testcase"})
DEFAULT_NUMERIC_FAMILIES = NUMERIC_FAMILIES

_EASING_BASES = (
    "quad",
    "cubic",
    "quart",
    "quint",
    "expo",
    "circ",
    "back",
    "elastic",
    "bounce",
)

#: Built-in ATL warpers from ``renpy/common/000atl.rpy`` and ``renpy/atl.py``.
ATL_WARPERS = frozenset(
    {"pause", "instant", "linear", "ease", "easein", "easeout"}
    | {
        f"{prefix}_{base}"
        for prefix in ("easein", "easeout", "ease")
        for base in _EASING_BASES
    }
)

_ATL_ROOTS = frozenset({"transform", "image", "scene", "camera"})
_TESTCASE_ROOTS = frozenset(
    {"testcase", "testsuite", "setup", "teardown", "before", "after"}
)
_AUDIO_STATEMENTS = frozenset({"play", "queue", "stop"})

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_INTEGER = re.compile(r"[-+]?\d+")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*\Z")
_FADE = re.compile(r"(?<![\w.])(?:fadein|fadeout)(?![\w.])")

#: A token that continues an expression rather than starting a new argument.
_EXPRESSION_CONTINUATION = frozenset("+-*/%&|^<>=!.,:()[]{}")
_EXPRESSION_WORDS = frozenset(
    {"and", "or", "not", "in", "is", "if", "else", "for", "while", "lambda"}
)


@dataclass(frozen=True)
class NumericOptions:
    """How numeric duration arguments should be rewritten."""

    style: NumericStyle = "bare"
    floats: bool = True
    families: frozenset[str] = DEFAULT_NUMERIC_FAMILIES
    warpers: frozenset[str] = ATL_WARPERS


@dataclass(frozen=True)
class NumericContext:
    """Physical lines that are inside ATL, screen or testcase blocks."""

    atl: frozenset[int] = frozenset()
    screen: frozenset[int] = frozenset()
    testcase: frozenset[int] = frozenset()


def build_numeric_context(analysis: Analysis) -> NumericContext:
    """Return the line sets used to recognise context-sensitive positions."""
    atl: set[int] = set()
    screen: set[int] = set()
    testcase: set[int] = set()

    for block in analysis.blocks:
        line = block.line
        word = line.first_word.rstrip(":")
        body = range(line.start_line + 1, block.end_line + 1)
        if _is_atl_root(line):
            atl.update(body)
        if word == "screen":
            screen.update(body)
        if word in _TESTCASE_ROOTS:
            testcase.update(body)

    return NumericContext(
        atl=frozenset(atl),
        screen=frozenset(screen),
        testcase=frozenset(testcase),
    )


def _is_atl_root(line: LogicalLine) -> bool:
    parts = line.text.split()
    if not parts:
        return False
    word = parts[0].rstrip(":")
    if word in _ATL_ROOTS:
        return True
    if word == "show":
        return len(parts) < 2 or parts[1] != "screen"
    return False


def normalize_numeric_args(
    text: str,
    line: int,
    context: NumericContext,
    options: NumericOptions,
) -> str:
    """Rewrite numeric duration arguments in one physical code line."""
    if not options.families:
        return text

    code, comment = _split_comment(text)
    result = code

    if "pause" in options.families:
        result = _rewrite_pause(result, options) or result
    if "audio" in options.families:
        result = _rewrite_audio(result, options) or result
    if "timer" in options.families and line in context.screen:
        result = _rewrite_timer(result, options) or result
    if "testcase" in options.families and line in context.testcase:
        result = _rewrite_testcase(result, options) or result
    if "atl" in options.families and line in context.atl:
        result = _rewrite_atl(result, options) or result

    if result == code:
        return text
    return result + comment


def _rewrite_pause(code: str, options: NumericOptions) -> str | None:
    word, end = _leading_word(code)
    if word != "pause":
        return None
    return _replace_argument(code, end, options, trailing="argument")


def _rewrite_audio(code: str, options: NumericOptions) -> str | None:
    word, _ = _leading_word(code)
    if word not in _AUDIO_STATEMENTS:
        return None

    masked = _mask_strings(code)
    result = code
    for match in reversed(list(_FADE.finditer(masked))):
        replaced = _replace_argument(result, match.end(), options, trailing="argument")
        if replaced is not None:
            result = replaced
    return result if result != code else None


def _rewrite_timer(code: str, options: NumericOptions) -> str | None:
    word, end = _leading_word(code)
    if word != "timer":
        return None
    return _replace_argument(code, end, options, trailing="argument")


def _rewrite_testcase(code: str, options: NumericOptions) -> str | None:
    word, end = _leading_word(code)
    if word not in {"pause", "timeout"}:
        return None
    return _replace_argument(code, end, options, trailing="end")


def _rewrite_atl(code: str, options: NumericOptions) -> str | None:
    # A bare number is a number statement: a pause for that duration.
    replaced = _replace_argument(code, 0, options, trailing="end")
    if replaced is not None:
        return replaced

    word, end = _leading_word(code)
    if word == "warp":
        function_end = _expression_end(code, end)
        if function_end <= end:
            return None
        return _replace_argument(code, function_end, options, trailing="argument")
    if word in {"time", "delay"}:
        return _replace_argument(code, end, options, trailing="end")
    if word in options.warpers and word != "pause":
        return _replace_argument(code, end, options, trailing="argument")
    return None


def _leading_word(text: str) -> tuple[str, int]:
    end = 0
    while end < len(text) and text[end] not in " \t":
        end += 1
    return text[:end], end


def _replace_argument(
    text: str,
    position: int,
    options: NumericOptions,
    *,
    trailing: Literal["end", "argument"],
) -> str | None:
    parsed = _parse_atom(text, position, options)
    if parsed is None:
        return None
    start, end, replacement = parsed
    if not _valid_rest(text[end:], trailing):
        return None
    return text[:start] + replacement + text[end:]


def _valid_rest(rest: str, trailing: Literal["end", "argument"]) -> bool:
    stripped = rest.strip()
    if trailing == "end":
        return not stripped
    if not rest:
        return True
    # A block form ends with a colon.
    if stripped == ":":
        return True
    # The argument must be followed by whitespace, not glued to an identifier.
    if rest[0] not in " \t":
        return False
    if not stripped:
        return True
    if stripped[0] in _EXPRESSION_CONTINUATION:
        return False
    match = re.match(r"[A-Za-z_]\w*", stripped)
    return not (match is not None and match.group(0) in _EXPRESSION_WORDS)


def _parse_atom(
    text: str,
    position: int,
    options: NumericOptions,
) -> tuple[int, int, str] | None:
    start = position
    while start < len(text) and text[start] in " \t":
        start += 1
    end = _atom_end(text, start)
    if end is None or end <= start:
        return None
    replacement = _format_atom(text[start:end], options)
    if replacement is None:
        return None
    return start, end, replacement


def _atom_end(text: str, start: int) -> int | None:
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif (ch in " \t:" or ch == "#") and depth == 0:
            break
        i += 1
    if depth:
        return None
    return i


def _format_atom(atom: str, options: NumericOptions) -> str | None:
    value = atom.strip()
    while value.startswith("(") and value.endswith(")") and _encloses_all(value):
        value = value[1:-1].strip()
    if _NUMBER.fullmatch(value) is None:
        return None
    if options.floats and _INTEGER.fullmatch(value) is not None:
        value += ".0"
    if options.style == "parens":
        return f"({value})"
    return value


def _encloses_all(value: str) -> bool:
    depth = 0
    for index, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0:
                return index == len(value) - 1
    return False


def _expression_end(text: str, position: int) -> int:
    """End of one whitespace-delimited expression, respecting brackets."""
    i = position
    while i < len(text) and text[i] in " \t":
        i += 1
    depth = 0
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch in " \t:" and depth == 0:
            break
        i += 1
    return i


def _split_comment(text: str) -> tuple[str, str]:
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        if ch in "\"'":
            quote = ch * 3 if text.startswith(ch * 3, i) else ch
            i += len(quote)
            continue
        if ch == "#":
            return text[:i], text[i:]
        i += 1
    return text, ""


def _mask_strings(text: str) -> str:
    """Replace string contents with spaces, keeping offsets and length."""
    chars = list(text)
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            chars[i] = " "
            if ch == "\\":
                if i + 1 < len(text):
                    chars[i + 1] = " "
                i += 2
                continue
            if text.startswith(quote, i):
                for k in range(i, i + len(quote)):
                    chars[k] = " "
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        if ch in "\"'":
            quote = ch * 3 if text.startswith(ch * 3, i) else ch
            for k in range(i, min(len(text), i + len(quote))):
                chars[k] = " "
            i += len(quote)
            continue
        i += 1
    return "".join(chars)


def coerce_style(value: object) -> NumericStyle | None:
    """Parse a style name from settings or the command line."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "").replace("_", "")
    if normalized == "bare":
        return "bare"
    if normalized in {"paren", "parens", "parentheses", "parenthesized"}:
        return "parens"
    return None


def coerce_families(value: object) -> frozenset[str] | None:
    """Parse a family list, ignoring names that are not known."""
    names = _name_list(value)
    if names is None:
        return None
    return frozenset(name for name in names if name in NUMERIC_FAMILIES)


def coerce_warpers(value: object) -> frozenset[str] | None:
    """Parse extra warper names and always keep the built-in warpers."""
    names = _name_list(value)
    if names is None:
        return None
    return ATL_WARPERS | frozenset(
        name for name in names if _IDENTIFIER.fullmatch(name) is not None
    )


def _name_list(value: object) -> list[str] | None:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = cast(Iterable[object], value)
        raw = [item for item in items if isinstance(item, str)]
    else:
        return None
    result: list[str] = []
    for item in raw:
        result.extend(part.strip() for part in item.split(",") if part.strip())
    return result
