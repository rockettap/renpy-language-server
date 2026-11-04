"""Bundled Ren'Py API documentation.

The data is generated from the MIT-licensed ``renpy.json`` shipped by
``renpy/vscode-language-renpy``. See ``NOTICE.md`` for attribution.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files


@dataclass(frozen=True)
class Builtin:
    """One Ren'Py function, class, action or variable."""

    name: str
    kind: str
    args: str
    type: str
    category: str
    documentation: str

    @property
    def signature(self) -> str:
        return f"{self.name}{self.args}" if self.args else self.name


@lru_cache(maxsize=1)
def builtins() -> dict[str, Builtin]:
    """Load and cache the bundled API table."""
    path = files("renpy_language_server.data").joinpath("renpy_api.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, Builtin] = {}
    for name, value in raw.items():
        result[name] = Builtin(
            name=name,
            kind=value["kind"],
            args=value["args"],
            type=value["type"],
            category=value["category"],
            documentation=value["doc"],
        )
    return result


def lookup(name: str) -> Builtin | None:
    """Return the built-in with exactly ``name``, if it exists."""
    return builtins().get(name)


def iter_builtins() -> tuple[Builtin, ...]:
    """Return every bundled built-in in a stable order."""
    return tuple(builtins().values())
