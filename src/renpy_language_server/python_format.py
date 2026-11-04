"""Optional Ruff formatting for Ren'Py ``python:`` block bodies.

This is the only formatter pass that can change more than whitespace, so it is
opt-in. Missing Ruff, invalid Python, a non-zero exit and timeouts all leave the
original block untouched.
"""

import logging
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from .analysis import analyze

log = logging.getLogger("renpy-language-server")

_PYTHON_BLOCK = re.compile(r"^(?:init\s+)?python(?:\s+early)?(?:\s+in\s+[\w.]+)?\s*:")
_TIMEOUT_SECONDS = 5.0
_ruff_warning_emitted = False

Runner = Callable[[str], str | None]


@dataclass(frozen=True)
class _Block:
    start_line: int
    end_line: int


def format_python_blocks(source: str, runner: Runner | None = None) -> str:
    """Format the body of every ``python:`` block with Ruff."""
    eol = "\r\n" if "\r\n" in source else "\n"
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)
    run = runner or _run_ruff

    replacements: list[tuple[int, int, list[str]]] = []
    for block in _python_blocks(normalized):
        body = lines[block.start_line : block.end_line + 1]
        if not body:
            continue
        indent = _body_indent(body)
        if indent is None:
            continue

        code = "".join(_dedent(line, indent) for line in body)
        formatted = run(code)
        if formatted is None:
            continue

        formatted = formatted.replace("\r\n", "\n").replace("\r", "\n")
        if not formatted.endswith("\n"):
            formatted += "\n"
        new_lines = [
            _reindent(line, indent) for line in formatted.splitlines(keepends=True)
        ]
        replacements.append((block.start_line, block.end_line, new_lines))

    if not replacements:
        return source

    result = list(lines)
    for start, end, new_lines in reversed(replacements):
        result[start : end + 1] = new_lines

    return "".join(result).replace("\n", eol)


def _python_blocks(source: str) -> list[_Block]:
    analysis = analyze(source)
    result: list[_Block] = []
    for block in analysis.blocks:
        if _PYTHON_BLOCK.match(block.line.text):
            result.append(
                _Block(
                    start_line=block.line.start_line + 1,
                    end_line=block.end_line,
                )
            )
    return result


def _body_indent(lines: list[str]) -> str | None:
    for line in lines:
        if line.strip():
            return line[: len(line) - len(line.lstrip(" \t"))]
    return None


def _dedent(line: str, indent: str) -> str:
    if not line.strip():
        return "\n" if line.endswith("\n") else ""
    if line.startswith(indent):
        return line[len(indent) :]
    return line.lstrip(" \t")


def _reindent(line: str, indent: str) -> str:
    if line in {"\n", ""}:
        return line
    return indent + line


def _run_ruff(code: str) -> str | None:
    global _ruff_warning_emitted

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--stdin-filename",
                "block.py",
                "-",
            ],
            input=code,
            text=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        if (
            not _ruff_warning_emitted
            and "No module named" in result.stderr
            and "ruff" in result.stderr
        ):
            _ruff_warning_emitted = True
            log.warning(
                "Ruff is not installed; python: blocks are left unchanged "
                "(install renpy-language-server[python-format])"
            )
        return None
    return result.stdout
