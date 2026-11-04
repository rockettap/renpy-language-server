"""Rewrite single-quoted string literals to double quotes.

Ren'Py accepts both quote styles. Rewriting a literal only changes its
delimiters, never its value, so the transform is safe by construction:

* a literal that contains an unescaped double quote is left untouched;
* an unterminated literal stops the pass, leaving the rest of the file alone;
* f-strings are scanned with brace tracking so nested expressions cannot end
  the outer literal early;
* comments are skipped, so quoted text inside a comment is not rewritten.

Triple-quoted literals keep their length (a triple-single literal becomes the
equivalent triple-double literal), which keeps positions stable for the callers
that map edits back to the original document.
"""

from bisect import bisect_right
from collections.abc import Collection

_PREFIX_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


def normalize_quotes(source: str, lines: Collection[int] | None = None) -> str:
    """Return *source* with single-quoted literals rewritten to double quotes.

    When *lines* is given, a literal is rewritten only if both of its delimiters
    sit on allowed 0-based physical lines. A multi-line literal is therefore
    converted atomically or not at all, which keeps range formatting from
    replacing only one side of it.
    """
    if "'" not in source:
        return source

    line_starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            line_starts.append(index + 1)

    chars = list(source)
    changed = False
    i = 0
    n = len(source)

    while i < n:
        char = source[i]

        if char == "#":
            newline = source.find("\n", i)
            if newline < 0:
                break
            i = newline + 1
            continue

        if char not in "\"'":
            i += 1
            continue

        quote = char * 3 if source.startswith(char * 3, i) else char
        end = _string_end(source, i, quote, _is_fstring(source, i))
        if end is None:
            break
        if quote[0] == "'":
            content = source[i + len(quote) : end - len(quote)]
            allowed = lines is None or (
                bisect_right(line_starts, i) - 1 in lines
                and bisect_right(line_starts, end - 1) - 1 in lines
            )
            if allowed and not _has_unescaped_double_quote(content):
                for offset in range(len(quote)):
                    chars[i + offset] = '"'
                    chars[end - len(quote) + offset] = '"'
                changed = True
        i = end

    return "".join(chars) if changed else source


def _is_fstring(source: str, index: int) -> bool:
    """True when the quote at *index* follows an ``f``/``F`` prefix."""
    j = index - 1
    prefix: list[str] = []
    while j >= 0 and source[j] in _PREFIX_CHARS:
        prefix.append(source[j].lower())
        j -= 1
    return "f" in prefix


def _string_end(source: str, start: int, quote: str, fstring: bool) -> int | None:
    """Index just past the closing *quote*, or ``None`` when unterminated."""
    i = start + len(quote)
    n = len(source)
    expressions = 0

    while i < n:
        char = source[i]

        if char == "\\":
            i += 2
            continue

        if expressions == 0 and source.startswith(quote, i):
            return i + len(quote)

        if fstring:
            if char == "{":
                if source.startswith("{{", i):
                    i += 2
                    continue
                expressions += 1
                i += 1
                continue
            if char == "}" and expressions > 0:
                if source.startswith("}}", i):
                    i += 2
                    continue
                expressions -= 1
                i += 1
                continue
            if expressions > 0 and char in "\"'":
                nested = char * 3 if source.startswith(char * 3, i) else char
                nested_end = _string_end(source, i, nested, _is_fstring(source, i))
                if nested_end is None:
                    return None
                i = nested_end
                continue

        i += 1

    return None


def _has_unescaped_double_quote(content: str) -> bool:
    i = 0
    n = len(content)
    while i < n:
        char = content[i]
        if char == "\\":
            i += 2
            continue
        if char == '"':
            return True
        i += 1
    return False
