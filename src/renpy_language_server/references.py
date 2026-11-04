"""Find every indexed reference to the symbol under the cursor."""

from lsprotocol import types

from .index import WorkspaceIndex
from .resolve import locate, occurrences
from .resolve import target as resolve_target


def references_at(
    uri: str,
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
    include_declaration: bool = True,
) -> list[types.Location]:
    """Return declarations and references for the symbol at the cursor.

    Declarations are included only when ``include_declaration`` is true.
    Unknown positions and unsupported symbol kinds return an empty list.
    """
    located = locate(uri, source, line, character, index)
    if located is None:
        return []
    target = resolve_target(located, index)
    if target is None:
        return []

    return [
        types.Location(
            uri=item.uri,
            range=types.Range(
                start=types.Position(line=item.line, character=item.start),
                end=types.Position(line=item.line, character=item.end),
            ),
        )
        for item in occurrences(target, index)
        if include_declaration or not item.write
    ]
