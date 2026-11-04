"""Literal label targets in ``jump`` and ``call`` statements."""

import re
from dataclasses import dataclass

_JUMP_CALL = re.compile(r"^[ \t]*(jump|call)[ \t]+(.+?)[ \t]*$")
_DYNAMIC = frozenset({"expression", "screen"})
_TARGET_STOP = frozenset({'"', "'", "$", "["})


@dataclass(frozen=True)
class Target:
    """A literal target and its span within one physical line."""

    name: str
    start: int
    end: int


def find_target(raw_line: str) -> Target | None:
    """Return the literal label target on ``raw_line``, if any."""
    match = _JUMP_CALL.match(raw_line.split("#", 1)[0].rstrip())
    if match is None:
        return None

    rest = match.group(2).strip()
    if not rest:
        return None

    first = rest.split(None, 1)[0]
    if first in _DYNAMIC or first[0] in _TARGET_STOP:
        return None

    name = first.split("(", 1)[0]
    if not name or name[0] in _TARGET_STOP:
        return None

    start = raw_line.find(name, match.start(2))
    if start < 0:
        return None
    return Target(name=name, start=start, end=start + len(name))


def target_at_position(raw_line: str, character: int) -> Target | None:
    """Return the target only when the cursor is on it."""
    target = find_target(raw_line)
    if target is None:
        return None
    if target.start <= character <= target.end:
        return target
    return None
