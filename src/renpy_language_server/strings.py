"""Scan Ren'Py source for physical-line string literals.

Semantic tokens and other providers need the spans of complete string
literals, including the ones that use the same quote on both sides. This
module only reports spans; it never interprets their contents.
"""

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class StringSpan:
    """One physical-line string literal."""

    start: int
    end: int
    content_start: int
    content_end: int
    quote: str
    closed: bool


def iter_string_spans(source: str) -> Iterator[tuple[int, StringSpan]]:
    """Yield closed single-line string literals with their line number."""
    quote: str | None = None
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    for line_index, raw in enumerate(normalized.split("\n")):
        spans, quote = _line_string_spans(raw, quote)
        for span in spans:
            yield line_index, span


def _line_string_spans(
    raw: str, quote: str | None
) -> tuple[list[StringSpan], str | None]:
    spans: list[StringSpan] = []
    index = 0
    start = -1
    content_start = -1
    continued = quote is not None
    length = len(raw)

    while index < length:
        if quote is None:
            char = raw[index]
            if char == "#":
                break
            if char in "\"'":
                quote = char * 3 if raw.startswith(char * 3, index) else char
                start = index
                content_start = index + len(quote)
                continued = False
                index += len(quote)
                continue
            index += 1
            continue

        if raw[index] == "\\":
            index += 2
            continue
        if raw.startswith(quote, index):
            end = index + len(quote)
            if not continued and start >= 0:
                spans.append(
                    StringSpan(
                        start=start,
                        end=end,
                        content_start=content_start,
                        content_end=index,
                        quote=quote,
                        closed=True,
                    )
                )
            quote = None
            start = -1
            content_start = -1
            index = end
            continue
        index += 1

    if quote is not None:
        # Ren'Py treats an unterminated single-quoted string as continuing on
        # the next physical line. Triple-quoted strings do the same.
        return spans, quote
    return spans, None
