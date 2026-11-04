"""Client-position helpers shared by LSP handlers."""

from lsprotocol import types
from pygls.workspace.position_codec import ServerTextPosition
from pygls.workspace.text_document import TextDocument


def client_position(
    doc: TextDocument,
    source: str,
    line: int,
    character: int,
) -> types.Position:
    """Convert a Python line/character pair to an LSP client position.

    ``TextDocument.client_position_at_offset`` maps an offset at the end of a
    file without a trailing newline to a non-existent next line. Converting the
    line/character pair directly avoids that edge case.
    """
    lines = source.splitlines(keepends=True)
    if line < len(lines):
        content = lines[line].rstrip("\r\n")
        if 0 <= character <= len(content):
            return doc.position_to_client_units(
                ServerTextPosition(line=line, character=character)
            )
    offset = sum(len(item) for item in lines[:line]) + character
    return doc.client_position_at_offset(min(offset, len(source)))
