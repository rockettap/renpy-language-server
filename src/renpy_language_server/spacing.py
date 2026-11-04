"""Small, token-aware inline spacing for Ren'Py Python statements.

Two entry points share one scanner:

* :func:`normalize_statement_spacing` handles the Python expression embedded in
  a Ren'Py statement (``$``, ``define``, ``default``, ``if``, ...);
* :func:`normalize_python_spacing` handles a line inside a ``python:`` block and
  therefore also normalizes arithmetic and bitwise operators.

Keyword arguments inside brackets are tightened (``f(color = "#fff")`` becomes
``f(color="#fff")``) while real assignments keep spaces around ``=``. Neither
entry point edits dialogue, screen properties, ATL lines, strings, comments,
slices or unary operators.
"""

_ASSIGNMENT_OPS = (
    "**=",
    "//=",
    ">>=",
    "<<=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "=",
)

_COMPARISON_OPS = ("==", "!=", "<=", ">=")

_ARITHMETIC_OPS = (
    "**",
    "//",
    "<<",
    ">>",
    "@",
    "+",
    "-",
    "*",
    "/",
    "%",
    "&",
    "|",
    "^",
)

_OPERATORS = tuple(
    sorted(
        _ASSIGNMENT_OPS + _COMPARISON_OPS + _ARITHMETIC_OPS,
        key=len,
        reverse=True,
    )
)
_COMPARISONS = frozenset(_COMPARISON_OPS)
_ASSIGNMENTS = frozenset(_ASSIGNMENT_OPS)
_PREFIXES = ("define", "default", "if", "elif", "while", "return", "assert")
_UNARY_KEYWORDS = frozenset(
    {
        "and",
        "assert",
        "await",
        "case",
        "del",
        "else",
        "for",
        "if",
        "in",
        "is",
        "lambda",
        "not",
        "or",
        "return",
        "while",
        "yield",
    }
)


def normalize_statement_spacing(text: str) -> str:
    """Normalize assignment/comparison spacing in one Ren'Py statement."""
    start = _python_rest_start(text)
    if start is None:
        return text
    return text[:start] + _normalize_operators(text[start:], arithmetic=False)


def normalize_python_spacing(text: str) -> str:
    """Normalize operators on one line inside a ``python:`` block."""
    stripped = text.lstrip()
    indent = len(text) - len(stripped)
    return text[:indent] + _normalize_operators(stripped, arithmetic=True)


def _python_rest_start(text: str) -> int | None:
    stripped = text.lstrip()
    indent = len(text) - len(stripped)
    if stripped.startswith("$"):
        return indent + 1

    for keyword in _PREFIXES:
        if stripped == keyword:
            return indent + len(keyword)
        if stripped.startswith(keyword) and stripped[len(keyword)].isspace():
            return indent + len(keyword)
    return None


def _normalize_operators(code: str, *, arithmetic: bool) -> str:
    out: list[str] = []
    quote: str | None = None
    depth = 0
    i = 0
    n = len(code)

    while i < n:
        char = code[i]

        if quote is not None:
            if char == "\\":
                out.append(code[i : i + 2])
                i += 2
            elif code.startswith(quote, i):
                out.append(quote)
                i += len(quote)
                quote = None
            else:
                out.append(char)
                i += 1
            continue

        if char == "#":
            out.append(code[i:])
            break

        if char in "\"'":
            quote = char * 3 if code.startswith(char * 3, i) else char
            out.append(quote)
            i += len(quote)
            continue

        if char in "([{":
            depth += 1
            out.append(char)
            i += 1
            continue

        if char in ")]}":
            depth = max(0, depth - 1)
            out.append(char)
            i += 1
            continue

        operator = _operator_at(code, i)
        if operator is not None:
            spacing = _operator_spacing(code, i, operator, out, depth, arithmetic)
            if spacing is True:
                _trim_trailing_spaces(out)
                if out and out[-1] not in "([{":
                    out.append(" ")
                out.append(operator)
                i += len(operator)
                while i < n and code[i].isspace():
                    i += 1
                if i < n:
                    out.append(" ")
                continue
            if spacing is False:
                _trim_trailing_spaces(out)
                out.append(operator)
                i += len(operator)
                while i < n and code[i].isspace():
                    i += 1
                continue

        out.append(char)
        i += 1

    return "".join(out)


def _operator_spacing(
    code: str,
    index: int,
    operator: str,
    out: list[str],
    depth: int,
    arithmetic: bool,
) -> bool | None:
    """Spacing around *operator*: ``True`` add, ``False`` remove, ``None`` keep."""
    if operator in _COMPARISONS:
        return True
    if operator in _ASSIGNMENTS:
        if depth == 0:
            return True
        # Inside brackets a bare ``=`` can only be a keyword argument or a
        # default parameter value; both are written without spaces. Compound
        # assignments such as ``+=`` are not valid there, so leave them alone.
        return False if operator == "=" else None
    if not arithmetic:
        return None

    previous = _previous_significant(out)
    following = _next_significant(code, index + len(operator))
    if not _is_operand_end(previous):
        return None
    if operator in {"+", "-"}:
        if _previous_word(out) in _UNARY_KEYWORDS:
            return None
        return True if _is_operand_start(following) else None
    return True if following else None


def _operator_at(code: str, index: int) -> str | None:
    for operator in _OPERATORS:
        if code.startswith(operator, index):
            return operator
    return None


def _previous_significant(out: list[str]) -> str:
    for char in reversed(out):
        if not char.isspace():
            return char
    return ""


def _previous_word(out: list[str]) -> str:
    word: list[str] = []
    started = False
    for char in reversed(out):
        if char.isalnum() or char == "_":
            word.append(char)
            started = True
        elif char.isspace():
            if started:
                break
        else:
            break
    return "".join(reversed(word))


def _next_significant(code: str, index: int) -> str:
    while index < len(code) and code[index].isspace():
        index += 1
    return code[index] if index < len(code) else ""


def _is_operand_end(char: str) -> bool:
    return bool(char) and (char.isalnum() or char in "_)]}'\"")


def _is_operand_start(char: str) -> bool:
    return bool(char) and (char.isalnum() or char in "_([{'\"~")


def _trim_trailing_spaces(out: list[str]) -> None:
    while out and out[-1].isspace():
        _ = out.pop()
