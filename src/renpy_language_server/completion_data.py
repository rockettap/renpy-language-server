"""Versioned completion data shared by the server and tests.

The keyword/value table is derived from the MIT-licensed ``renpyauto.json`` in
``renpy/vscode-language-renpy``. The screen element, property and transition
lists are a curated snapshot of Ren'Py's screen language. Keeping them in JSON
avoids scattering vocabulary across the completion engine.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, cast


@dataclass(frozen=True)
class CompletionData:
    """Loaded completion vocabulary."""

    keyword_values: Mapping[str, str]
    screen_elements: tuple[str, ...]
    screen_properties: Mapping[str, tuple[str, ...]]
    atl_properties: tuple[str, ...]
    transforms: tuple[str, ...]
    transitions: tuple[str, ...]
    audio_channels: tuple[str, ...]

    def properties_for(self, element: str) -> tuple[str, ...]:
        """Return common properties followed by element-specific ones."""
        common = self.screen_properties.get("common", ())
        specific = self.screen_properties.get(element, ())
        return _unique(common + specific)

    def values_for(self, keyword: str) -> tuple[str, ...]:
        """Return literal completion values for a keyword/property."""
        raw = self.keyword_values.get(keyword)
        if not raw:
            return ()
        result: list[str] = []
        for item in raw.split("|"):
            item = item.strip()
            if not item or item.startswith("{"):
                continue
            result.append(item)
        return tuple(result)


@lru_cache(maxsize=1)
def data() -> CompletionData:
    """Load and cache the bundled completion data."""
    path = files("renpy_language_server.data").joinpath("completion.json")
    raw = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    properties = cast(dict[str, list[str]], raw["screen_properties"])
    return CompletionData(
        keyword_values=cast(dict[str, str], raw["keyword_values"]),
        screen_elements=tuple(cast(list[str], raw["screen_elements"])),
        screen_properties={key: tuple(values) for key, values in properties.items()},
        atl_properties=tuple(cast(list[str], raw["atl_properties"])),
        transforms=tuple(cast(list[str], raw["transforms"])),
        transitions=tuple(cast(list[str], raw["transitions"])),
        audio_channels=tuple(cast(list[str], raw["audio_channels"])),
    )


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
