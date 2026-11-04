"""Command line entry point.

``renpy-language-server``                 start the language server on stdio
``renpy-language-server dap``             start the launch-only debug adapter on stdio
``renpy-language-server format FILE...``  format files in place (``--check``, ``--diff``)
"""

import difflib
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .formatter import FormatOptions, format_source

app = typer.Typer(
    name="renpy-language-server",
    help="Ren'Py language server.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"renpy-language-server {__version__}")
        raise typer.Exit


@app.callback()
def root(
    ctx: typer.Context,
    *,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
    stdio: Annotated[
        bool,
        typer.Option("--stdio", help="Accepted for client compatibility."),
    ] = False,
) -> None:
    """Start the language server on stdio (default when no subcommand is given)."""
    _ = (version, stdio)
    if ctx.invoked_subcommand is None:
        from .server import run  # imported lazily: the CLI should start fast

        run()


def _iter_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.rpy")))
            files.extend(sorted(path.rglob("*.rpym")))
        else:
            files.append(path)
    return files


def _format_impl(
    paths: list[str],
    *,
    check: bool,
    diff: bool,
    indent: int,
    spacing: bool,
    quotes: bool,
    python_format: bool,
) -> int:
    options = FormatOptions(
        indent=indent,
        normalize_spacing=spacing,
        normalize_quotes=quotes,
        format_python=python_format,
    )

    if paths == ["-"]:
        _ = sys.stdout.write(format_source(sys.stdin.read(), options))
        return 0

    changed = 0
    for path in _iter_files(paths):
        with open(path, encoding="utf-8", newline="") as fh:
            old = fh.read()
        new = format_source(old, options)
        if old == new:
            continue
        changed += 1
        if diff:
            _ = sys.stdout.writelines(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            )
        elif check:
            print(f"would reformat {path}", file=sys.stderr)
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                _ = fh.write(new)
            print(f"reformatted {path}", file=sys.stderr)

    return 1 if changed and (check or diff) else 0


@app.command()
def dap() -> None:
    """Start the launch-only Debug Adapter Protocol server on stdio."""
    from .dap import run  # imported lazily: the CLI should start fast

    raise typer.Exit(run())


@app.command()
def format(
    paths: Annotated[
        list[str],
        typer.Argument(help="Files or directories; '-' reads stdin."),
    ],
    *,
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit 1 if any file would change."),
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Print a diff instead of writing."),
    ] = False,
    indent: Annotated[
        int,
        typer.Option("--indent", help="Spaces per indentation level."),
    ] = 4,
    spacing: Annotated[
        bool,
        typer.Option(
            "--spacing/--no-spacing",
            help="Normalize spacing around operators in Python statements.",
        ),
    ] = True,
    python_format: Annotated[
        bool,
        typer.Option(
            "--python/--no-python",
            help="Format python: blocks with Ruff (not whitespace-only).",
        ),
    ] = False,
    quotes: Annotated[
        bool,
        typer.Option(
            "--quotes/--no-quotes",
            help="Rewrite single-quoted strings to double quotes.",
        ),
    ] = True,
) -> None:
    """Format .rpy files."""
    rc = _format_impl(
        paths,
        check=check,
        diff=diff,
        indent=indent,
        spacing=spacing,
        quotes=quotes,
        python_format=python_format,
    )
    raise typer.Exit(rc)


def main(argv: list[str] | None = None) -> int:
    """Entry point for programmatic use and tests.

    Returns the process exit code (0 = success).
    When no subcommand is given the language server is started.
    """
    try:
        app(args=argv, standalone_mode=True)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0
