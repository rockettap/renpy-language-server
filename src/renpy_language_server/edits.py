"""Turn "old text -> new text" into minimal line-based LSP edits.

Returning a single whole-document replacement makes editors lose the cursor
position and folds; line-level edits avoid that.
"""

import difflib
from typing import NamedTuple


class Edit(NamedTuple):
    start_line: int
    start_char: int
    end_line: int
    end_char: int
    new_text: str


def compute_edits(old: str, new: str) -> list[Edit]:
    if old == new:
        return []
    a = old.splitlines(keepends=True)
    b = new.splitlines(keepends=True)

    def pos(line_index: int) -> tuple[int, int]:
        # A position "after the last line" is only valid when that line ended
        # with a newline; otherwise point at the end of the last line.
        if line_index >= len(a) and a and not a[-1].endswith(("\n", "\r")):
            return len(a) - 1, len(a[-1])
        return line_index, 0

    edits: list[Edit] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        (sl, sc), (el, ec) = pos(i1), pos(i2)
        edits.append(Edit(sl, sc, el, ec, "".join(b[j1:j2])))
    return edits


def compute_edits_in_range(
    old: str, new: str, start_line: int, end_line: int
) -> list[Edit]:
    """Keep only the whole-document edits that touch the requested lines."""
    result: list[Edit] = []
    for edit in compute_edits(old, new):
        edit_end = edit.end_line
        if edit.end_char == 0 and edit.end_line > edit.start_line:
            edit_end -= 1
        if edit.start_line <= end_line and edit_end >= start_line:
            result.append(edit)
    return result


def apply_edits(text: str, edits: list[Edit]) -> str:
    """Apply edits the way an LSP client would (used by tests)."""
    lines = text.splitlines(keepends=True)

    def offset(line: int, char: int) -> int:
        if line >= len(lines):
            return len(text)
        return sum(len(x) for x in lines[:line]) + char

    out = text
    for e in sorted(edits, key=lambda e: (e.start_line, e.start_char), reverse=True):
        s = offset(e.start_line, e.start_char)
        t = offset(e.end_line, e.end_char)
        out = out[:s] + e.new_text + out[t:]
    return out
