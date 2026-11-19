# Annotation Policy

The project supports Python 3.10 and newer and does **not** use
`from __future__ import annotations`.

## Why

On Python 3.10–3.13, annotations are evaluated when a module, class, or
function is defined. Deferred evaluation only becomes the default in Python
3.14 (PEP 649). The future import is therefore unnecessary here, and keeping it
would hide forward-reference mistakes until runtime on older interpreters.

Removing it is safe because annotations are still checked by Pyright and the
CI matrix runs Python 3.10, where eager evaluation exposes unresolved names
immediately.

## Rules

1. Do not add `from __future__ import annotations`. Ruff rule `TID251` bans it.
2. Quote forward references inside annotations:

   ```python
   def _no_children() -> "list[Block]":
       return []


   @dataclass
   class Block:
       parent: "Block | None"
       children: "list[Block]" = field(default_factory=_no_children)
   ```

3. Quote types used outside annotations, such as aliases, even on Python 3.14:

   ```python
   from typing import TypeAlias

   BlockList: TypeAlias = "list[Block]"
   ```

4. Import every name used by an annotation at runtime. Do not move those
   imports under `if TYPE_CHECKING:` while Python 3.10–3.13 remain supported.
5. Prefer built-in generics (`list[str]`, `dict[str, int]`) and `X | None`
   unions. They are valid at runtime on Python 3.10.

## Enforcement

- `[tool.ruff.lint.flake8-tidy-imports.banned-api]` rejects the future import.
- `[tool.pyright] pythonVersion = "3.10"` makes local type checking use the
  minimum supported version.
- CI runs the test suite on Python 3.10 through 3.14.

If the minimum supported version ever becomes 3.14, update this document,
remove the quotes from `analysis.py`, and set the Ruff and Pyright target
versions to 3.14.
