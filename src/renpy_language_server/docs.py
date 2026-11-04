"""Collect comment documentation above declarations."""

from collections.abc import Sequence


def comment_block(raw_lines: Sequence[str], line: int) -> str:
    """Return the contiguous ``#`` comment block immediately above ``line``."""
    if line <= 0 or line > len(raw_lines):
        return ""

    index = line - 1
    block: list[str] = []
    while index >= 0:
        text = raw_lines[index].strip()
        if not text.startswith("#"):
            break
        block.append(text[1:].lstrip())
        index -= 1

    block.reverse()
    return "\n".join(block).strip()
