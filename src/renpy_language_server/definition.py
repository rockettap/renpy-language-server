"""Resolve declarations at the cursor and image assets."""

from .assets import Asset, AssetIndex
from .index import Symbol, WorkspaceIndex, parse_document, utf16_length
from .resolve import declarations, locate
from .resolve import target as resolve_target
from .targets import find_target, target_at_position

__all__ = [
    "definitions_at",
    "find_definition",
    "find_image_definition",
    "find_target",
    "target_at_position",
]


def definitions_at(
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> list[Symbol]:
    """Return declarations for the symbol at ``line``/``character``.

    Covers labels, screens, transforms, images, layered images, characters,
    styles, variables and unambiguous Python classes/members. The cursor may be
    on a declaration or a reference.
    """
    located = locate("", source, line, character, index)
    if located is None:
        return []
    target = resolve_target(located, index)
    if target is None:
        return []
    return declarations(target.family, target.name, index, target.container)


def find_definition(
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
) -> list[Symbol]:
    """Return declarations for the symbol at ``line``/``character``."""
    return definitions_at(source, line, character, index)


def find_image_definition(
    source: str,
    line: int,
    character: int,
    index: WorkspaceIndex,
    assets: AssetIndex,
) -> Symbol | Asset | None:
    """Return a declared image or automatic asset used at the cursor."""
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if line < 0 or line >= len(raw_lines):
        return None
    raw = raw_lines[line]
    if character < 0 or character > len(raw):
        return None

    cursor = utf16_length(raw[:character])
    document = parse_document("", source)
    for reference in document.references:
        if reference.kind != "image" or reference.line != line:
            continue
        if not reference.character <= cursor <= reference.end_character:
            continue
        symbols = index.find("image", reference.name) + index.find(
            "layeredimage", reference.name
        )
        if symbols:
            return symbols[0]
        return assets.find_image(reference.name)
    return None
