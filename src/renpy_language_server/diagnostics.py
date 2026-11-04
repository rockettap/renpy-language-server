"""Conservative, configurable diagnostics for Ren'Py projects.

Every rule can be set to ``error``, ``warning`` or ``off`` through the
``diagnostic_rules`` setting. Workspace-wide rules (duplicate labels, unknown
images, undefined screens and store variables) use the shared
:class:`~renpy_language_server.index.WorkspaceIndex` and the optional automatic
:class:`~renpy_language_server.assets.AssetIndex`.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from lsprotocol import types
from pygls.uris import to_fs_path

from .analysis import Analysis, analyze
from .assets import AssetIndex
from .definition import find_target
from .index import (
    DocumentIndex,
    WorkspaceIndex,
    label_contexts,
    mask_code,
    parse_document,
    qualified_local_name,
    utf16_length,
)
from .settings import (
    DEFAULT_DIAGNOSTIC_RULES,
    DiagnosticSeveritySetting,
    Settings,
)

SOURCE = "renpy-language-server"

_RULE_CODES = {
    "indentation": "renpy-language-server.indentation",
    "tabs": "renpy-language-server.tabs",
    "filename": "renpy-language-server.filename",
    "invalid_variable": "renpy-language-server.invalid-variable",
    "reserved_names": "renpy-language-server.reserved-names",
    "comparison": "renpy-language-server.comparison",
    "stray_dollar": "renpy-language-server.stray-dollar",
    "obsolete_api": "renpy-language-server.obsolete-api",
    "undefined_persistent": "renpy-language-server.undefined-persistent",
    "undefined_store": "renpy-language-server.undefined-store",
    "duplicate_label": "renpy-language-server.duplicate-label",
    "unknown_label": "renpy-language-server.unknown-label",
    "unknown_image": "renpy-language-server.unknown-image",
    "undefined_screen": "renpy-language-server.undefined-screen",
}

INDENTATION = _RULE_CODES["indentation"]
TABS = _RULE_CODES["tabs"]
FILENAME = _RULE_CODES["filename"]
INVALID_VARIABLE = _RULE_CODES["invalid_variable"]
RESERVED_NAMES = _RULE_CODES["reserved_names"]
COMPARISON = _RULE_CODES["comparison"]
STRAY_DOLLAR = _RULE_CODES["stray_dollar"]
OBSOLETE_API = _RULE_CODES["obsolete_api"]
UNDEFINED_PERSISTENT = _RULE_CODES["undefined_persistent"]
UNDEFINED_STORE = _RULE_CODES["undefined_store"]
DUPLICATE_LABEL = _RULE_CODES["duplicate_label"]
UNKNOWN_LABEL = _RULE_CODES["unknown_label"]
UNKNOWN_IMAGE = _RULE_CODES["unknown_image"]
UNDEFINED_SCREEN = _RULE_CODES["undefined_screen"]

_SEVERITIES = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
}

_RENPY_STORE = frozenset(
    {
        "adv",
        "default_mouse",
        "main_menu",
        "menu",
        "mouse_visible",
        "name_only",
        "narrator",
        "say",
        "save_name",
        "persistent",
        "_autosave",
        "_confirm_quit",
        "_dismiss_pause",
        "_game_menu_screen",
        "_history",
        "_history_list",
        "_ignore_action",
        "_menu",
        "_quit_slot",
        "_rollback",
        "_screenshot_pattern",
        "_skipping",
        "_version",
        "_window",
        "_window_auto",
        "_window_subtitle",
        "_in_replay",
        "_live2d_fade",
    }
)

_PYTHON_RESERVED = frozenset(
    """
    ArithmeticError AssertionError AttributeError BaseException BufferError
    BytesWarning DeprecationWarning EOFError Ellipsis EnvironmentError Exception
    False FloatingPointError FutureWarning GeneratorExit IOError ImportError
    ImportWarning IndentationError IndexError KeyError KeyboardInterrupt
    LookupError MemoryError NameError None NoneType NotImplemented
    NotImplementedError OSError OverflowError PendingDeprecationWarning
    ReferenceError RuntimeError RuntimeWarning StandardError StopIteration
    SyntaxError SyntaxWarning SystemError SystemExit TabError True TypeError
    UnboundLocalError UnicodeDecodeError UnicodeEncodeError UnicodeError
    UnicodeTranslateError UnicodeWarning UserWarning ValueError Warning
    ZeroDivisionError abs all any apply basestring bin bool buffer bytearray
    bytes callable chr classmethod cmp coerce compile complex copyright credits
    delattr dict dir divmod enumerate eval execfile exit file filter float format
    frozenset getattr globals hasattr hash help hex id input int intern isinstance
    issubclass iter len license list locals long map max memoryview min next
    object oct open ord pow print property quit range raw_input reduce reload
    repr reversed round set setattr slice sorted staticmethod str sum super
    tuple type unichr unicode vars xrange zip
    """.split()  # noqa: SIM905 - a readable block is easier to audit.
)

_OBSOLETE_API = tuple(
    sorted(
        {
            "LiveCrop",
            "LiveComposite",
            "Tooltip",
            "im.Rotozoom",
            "im.ImageBase",
            "im.ramp",
            "im.Map",
            "im.Flip",
            "im.math",
            "im.expands_bounds",
            "im.threading",
            "im.zipfile",
            "im.Recolor",
            "im.Color",
            "im.io",
            "im.Alpha",
            "im.Data",
            "im.Image",
            "im.Twocolor",
            "im.MatrixColor",
            "im.free_memory",
            "im.Tile",
            "im.FactorScale",
            "im.Sepia",
            "im.Crop",
            "im.AlphaMask",
            "im.Blur",
            "im.tobytes",
            "im.matrix",
            "im.Grayscale",
            "ui.add",
            "ui.bar",
            "ui.imagebutton",
            "ui.input",
            "ui.key",
            "ui.label",
            "ui.null",
            "ui.text",
            "ui.textbutton",
            "ui.timer",
            "ui.vbar",
            "ui.hotspot",
            "ui.hotbar",
            "ui.spritemanager",
            "ui.button",
            "ui.frame",
            "ui.transform",
            "ui.window",
            "ui.drag",
            "ui.fixed",
            "ui.grid",
            "ui.hbox",
            "ui.side",
            "ui.vbox",
            "ui.imagemap",
            "ui.draggroup",
        },
        key=len,
        reverse=True,
    )
)
OBSOLETE_API_NAMES = frozenset(_OBSOLETE_API)
_OBSOLETE_RE = re.compile(
    r"(?<![\w.])(?:" + "|".join(re.escape(item) for item in _OBSOLETE_API) + r")(?!\w)"
)
_DECLARATION_RE = re.compile(r"^\s*(?:default|define)(?:\s+[-+]?\d+)?\s+([A-Za-z_]\w*)")
_INVALID_DECLARATION_RE = re.compile(
    r"^\s*(?:default|define)(?:\s+[-+]?\d+)?\s+([^A-Za-z\s][A-Za-z0-9_]*)"
)
_COMPARISON_RE = re.compile(r"\b(?:if|while)\s+\w+\s*(=)(?!=)\s*\w+")
_FILENAME_IGNORE_RE = re.compile(
    r"^\s*#\s*@Ren'?Py-Filename\s*:\s*(?:Ignore|Disable)", re.IGNORECASE
)

_BUILTIN_SCREENS = frozenset(
    {
        "say",
        "choice",
        "quick_menu",
        "navigation",
        "main_menu",
        "game_menu",
        "load",
        "save",
        "preferences",
        "history",
        "help",
        "about",
        "confirm",
        "skip_indicator",
        "notify",
        "nvl",
        "input",
        "bubble",
    }
)


def diagnostics_for_document(
    source: str,
    index: WorkspaceIndex,
    settings: Settings,
    uri: str = "",
    assets: AssetIndex | None = None,
) -> list[types.Diagnostic]:
    """Run every enabled diagnostic rule for one document."""
    if not settings.diagnostics:
        return []

    analysis = analyze(source, default_indent=settings.indent)
    raw_lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    document = index.get(uri) if uri else None
    if document is None or document.source != source:
        document = parse_document(uri, source, options=index.options)

    result: list[types.Diagnostic] = []
    for rule in _RULE_CODES:
        severity = _severity(settings, rule)
        if severity is None:
            continue
        if rule == "indentation":
            result += indentation_diagnostics(analysis, raw_lines, severity)
        elif rule == "tabs":
            result += tabs_diagnostics(raw_lines, analysis, severity)
        elif rule == "filename":
            result += filename_diagnostics(source, raw_lines, uri, severity)
        elif rule == "invalid_variable":
            result += invalid_variable_diagnostics(raw_lines, analysis, severity)
        elif rule == "reserved_names":
            result += reserved_name_diagnostics(raw_lines, analysis, severity)
        elif rule == "comparison":
            result += comparison_diagnostics(raw_lines, analysis, severity)
        elif rule == "stray_dollar":
            result += stray_dollar_diagnostics(raw_lines, analysis, severity)
        elif rule == "obsolete_api":
            result += obsolete_api_diagnostics(raw_lines, analysis, severity)
        elif rule == "undefined_persistent":
            result += undefined_persistent_diagnostics(document, index, severity)
        elif rule == "undefined_store":
            result += undefined_store_diagnostics(document, index, severity)
        elif rule == "duplicate_label":
            result += duplicate_label_diagnostics(document, index, severity)
        elif rule == "unknown_label":
            result += unknown_label_diagnostics(analysis, raw_lines, index, severity)
        elif rule == "unknown_image":
            result += unknown_image_diagnostics(document, index, assets, severity)
        elif rule == "undefined_screen":
            result += undefined_screen_diagnostics(document, index, severity)
    return result


def indentation_diagnostics(
    analysis: Analysis,
    raw_lines: Sequence[str],
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn when a code line's indent does not match its block depth."""
    unit = max(analysis.indent_unit, 1)
    result: list[types.Diagnostic] = []

    for line in analysis.lines:
        if line.kind != "code":
            continue

        expected = line.depth * unit
        if line.indent != expected:
            result.append(
                _indent_diagnostic(
                    line.start_line,
                    raw_lines,
                    INDENTATION,
                    f"Indentation is {line.indent} spaces, expected {expected}.",
                    severity,
                )
            )
            continue

        if not line.opens_block:
            continue

        block = analysis.block_at(line.start_line)
        if block is not None and block.end_line <= line.end_line:
            result.append(
                _indent_diagnostic(
                    line.start_line,
                    raw_lines,
                    INDENTATION,
                    f"Expected an indented body of {unit} spaces.",
                    severity,
                )
            )

    return result


def tabs_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about tab characters used for indentation."""
    result: list[types.Diagnostic] = []
    for line, raw in enumerate(raw_lines):
        if not raw.strip():
            continue
        logical = analysis.line_at(line)
        if logical is not None and logical.start_line != line:
            # Continuation text can be inside a string literal or a bracket.
            continue
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" not in leading:
            continue
        start = leading.index("\t")
        end = start
        while end < len(leading) and leading[end] == "\t":
            end += 1
        result.append(
            _diagnostic(
                line,
                raw,
                start,
                end,
                TABS,
                "Tab characters are not allowed. Indentation must consist of spaces.",
                severity,
            )
        )
    return result


def filename_diagnostics(
    source: str,
    raw_lines: Sequence[str],
    uri: str,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn when a file name is unsuitable for Ren'Py's load order."""
    if not uri:
        return []
    path = to_fs_path(uri)
    if path is None:
        return []
    normalized = str(path).replace("\\", "/")
    if "/renpy/common/" in normalized:
        return []
    name = Path(path).name
    if not name or (name[0].isalnum() and not name.startswith("00")):
        return []

    first = raw_lines[0] if raw_lines else ""
    if _FILENAME_IGNORE_RE.match(first):
        return []

    last = max(len(raw_lines) - 1, 0)
    last_length = utf16_length(raw_lines[last]) if raw_lines else 0
    return [
        types.Diagnostic(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=last, character=last_length),
            ),
            message=(
                "Filenames must begin with a letter or number, but may not begin "
                "with '00' as Ren'Py uses such files for its own purposes."
            ),
            severity=_SEVERITIES[severity],
            source=SOURCE,
            code=FILENAME,
        )
    ]


def invalid_variable_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about ``define`` / ``default`` names that cannot be variables."""
    result: list[types.Diagnostic] = []
    for line in _logical_code_lines(raw_lines, analysis):
        masked = mask_code(line.text)
        match = _INVALID_DECLARATION_RE.match(masked)
        if match is None:
            continue
        name = match.group(1)
        if name in _RENPY_STORE:
            continue
        start = line.start + match.start(1)
        result.append(
            _diagnostic(
                line.index,
                raw_lines[line.index],
                start,
                start + len(name),
                INVALID_VARIABLE,
                f'"{name}": Variables must begin with a letter.',
                severity,
            )
        )
    return result


def reserved_name_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about Ren'Py-reserved and Python-reserved declaration names."""
    result: list[types.Diagnostic] = []
    for line in _logical_code_lines(raw_lines, analysis):
        masked = mask_code(line.text)
        match = _DECLARATION_RE.match(masked)
        if match is None:
            continue
        name = match.group(1)
        if name.startswith("_"):
            message = (
                f'"{name}": Variables may not begin with a single underscore; '
                "Ren'Py reserves such variables for its own purposes."
            )
        elif name in _PYTHON_RESERVED:
            message = (
                f'"{name}": is a Python reserved name, type, or function. '
                "Using it as a variable can lead to obscure problems."
            )
        else:
            continue
        start = line.start + match.start(1)
        result.append(
            _diagnostic(
                line.index,
                raw_lines[line.index],
                start,
                start + len(name),
                RESERVED_NAMES,
                message,
                severity,
            )
        )
    return result


def comparison_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about assignment ``=`` used where comparison ``==`` is meant."""
    result: list[types.Diagnostic] = []
    for line in _logical_code_lines(raw_lines, analysis):
        masked = mask_code(line.text)
        for match in _COMPARISON_RE.finditer(masked):
            start = line.start + match.start(1)
            result.append(
                _diagnostic(
                    line.index,
                    raw_lines[line.index],
                    start,
                    start + 1,
                    COMPARISON,
                    '"=" is the assignment operator. Use "==" for comparison.',
                    severity,
                )
            )
    return result


def stray_dollar_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about a ``$`` that is not the first token on its line."""
    result: list[types.Diagnostic] = []
    for line in _logical_code_lines(raw_lines, analysis):
        masked = mask_code(line.text)
        leading = len(masked) - len(masked.lstrip())
        position = masked.find("$", leading + 1)
        if position < 0:
            continue
        start = line.start + position
        result.append(
            _diagnostic(
                line.index,
                raw_lines[line.index],
                start,
                start + 1,
                STRAY_DOLLAR,
                '"$" starts a one-line Python statement, but was found in the middle of the line.',
                severity,
            )
        )
    return result


def obsolete_api_diagnostics(
    raw_lines: Sequence[str],
    analysis: Analysis,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about APIs that Ren'Py has removed or replaced."""
    result: list[types.Diagnostic] = []
    for line in _logical_code_lines(raw_lines, analysis):
        masked = mask_code(line.text)
        for match in _OBSOLETE_RE.finditer(masked):
            start = line.start + match.start()
            name = match.group(0)
            result.append(
                _diagnostic(
                    line.index,
                    raw_lines[line.index],
                    start,
                    start + len(name),
                    OBSOLETE_API,
                    f'"{name}": This function is obsolete or outdated.',
                    severity,
                )
            )
    return result


def undefined_persistent_diagnostics(
    document: DocumentIndex,
    index: WorkspaceIndex,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn when a persistent variable was never defined or defaulted."""
    declared = {symbol.name for symbol in index.by_kind("persistent")}
    declared.update(
        symbol.name for symbol in document.symbols if symbol.kind == "persistent"
    )
    return _undefined_references(
        document,
        "persistent",
        declared,
        UNDEFINED_PERSISTENT,
        lambda name: (
            f'"persistent.{name}": This persistent variable has not been '
            "defaulted or defined."
        ),
        severity,
        ignore_underscore=True,
    )


def undefined_store_diagnostics(
    document: DocumentIndex,
    index: WorkspaceIndex,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn when a ``store.`` variable was never defined or defaulted."""
    declared = {
        symbol.name
        for symbol in index.all_symbols()
        if symbol.kind
        in {"variable", "class", "callable", "store", "method", "field", "property"}
    }
    declared.update(
        symbol.name
        for symbol in document.symbols
        if symbol.kind
        in {"variable", "class", "callable", "store", "method", "field", "property"}
    )
    return _undefined_references(
        document,
        "store",
        declared,
        UNDEFINED_STORE,
        lambda name: (
            f'"store.{name}": Use of a store variable that has not been defaulted.'
        ),
        severity,
        ignore_underscore=True,
        ignore_reserved=True,
    )


def duplicate_label_diagnostics(
    document: DocumentIndex,
    index: WorkspaceIndex,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about labels declared more than once in the workspace."""
    labels = index.labels()
    local = [symbol for symbol in document.symbols if symbol.kind == "label"]
    result: list[types.Diagnostic] = []

    for symbol in local:
        others = [
            item
            for item in labels.get(symbol.name, [])
            if not (item.uri == symbol.uri and item.line == symbol.line)
        ]
        if not others:
            continue
        other = others[0]
        path = to_fs_path(other.uri)
        location = f"{Path(path).name}:{other.line + 1}" if path else other.uri
        source_name = symbol.source_name or symbol.name
        result.append(
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=symbol.line, character=symbol.character),
                    end=types.Position(
                        line=symbol.line,
                        character=symbol.character + utf16_length(source_name),
                    ),
                ),
                message=f"Duplicate label '{symbol.name}'. Also declared at {location}.",
                severity=_SEVERITIES[severity],
                source=SOURCE,
                code=DUPLICATE_LABEL,
            )
        )
    return result


def unknown_label_diagnostics(
    analysis: Analysis,
    raw_lines: Sequence[str],
    index: WorkspaceIndex,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn when a literal ``jump`` / ``call`` target is not indexed."""
    result: list[types.Diagnostic] = []
    contexts = label_contexts(analysis)

    for line in analysis.lines:
        if line.kind != "code" or line.start_line >= len(raw_lines):
            continue

        raw = raw_lines[line.start_line]
        target = find_target(raw)
        if target is None:
            continue

        context = contexts[line.start_line] if line.start_line < len(contexts) else None
        name = qualified_local_name(target.name, context)
        if name is None:
            continue
        if index.find("label", name):
            continue

        start = utf16_length(raw[: target.start])
        result.append(
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=line.start_line, character=start),
                    end=types.Position(
                        line=line.start_line,
                        character=start + utf16_length(target.name),
                    ),
                ),
                message=f"Unknown label '{name}'.",
                severity=_SEVERITIES[severity],
                source=SOURCE,
                code=UNKNOWN_LABEL,
            )
        )

    return result


def unknown_image_diagnostics(
    document: DocumentIndex,
    index: WorkspaceIndex,
    assets: AssetIndex | None,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about ``show`` / ``scene`` / ``hide`` targets that do not exist."""
    result: list[types.Diagnostic] = []
    for reference in document.references:
        if reference.kind != "image":
            continue
        name = reference.name
        if index.find("image", name) or index.find("layeredimage", name):
            continue
        if assets is not None and assets.find_image(name):
            continue
        result.append(
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(
                        line=reference.line, character=reference.character
                    ),
                    end=types.Position(
                        line=reference.line, character=reference.end_character
                    ),
                ),
                message=f"Unknown image '{name}'.",
                severity=_SEVERITIES[severity],
                source=SOURCE,
                code=UNKNOWN_IMAGE,
            )
        )
    return result


def undefined_screen_diagnostics(
    document: DocumentIndex,
    index: WorkspaceIndex,
    severity: DiagnosticSeveritySetting = "warning",
) -> list[types.Diagnostic]:
    """Warn about ``call screen`` / ``use`` targets that do not exist."""
    declared = {symbol.name for symbol in index.by_kind("screen")}
    declared.update(
        symbol.name for symbol in document.symbols if symbol.kind == "screen"
    )
    declared.update(_BUILTIN_SCREENS)
    result: list[types.Diagnostic] = []
    for reference in document.references:
        if reference.kind not in {"screen", "use"}:
            continue
        name = reference.name
        if name in declared or name.startswith("_"):
            continue
        result.append(
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(
                        line=reference.line, character=reference.character
                    ),
                    end=types.Position(
                        line=reference.line, character=reference.end_character
                    ),
                ),
                message=f"Undefined screen '{name}'.",
                severity=_SEVERITIES[severity],
                source=SOURCE,
                code=UNDEFINED_SCREEN,
            )
        )
    return result


class _LogicalCodeLine:
    """One physical code line with its offset inside the source."""

    __slots__ = ("index", "start", "text")

    def __init__(self, index: int, start: int, text: str) -> None:
        self.index = index
        self.start = start
        self.text = text


def _logical_code_lines(
    raw_lines: Sequence[str], analysis: Analysis
) -> Iterable[_LogicalCodeLine]:
    """Yield physical code lines that start a logical Ren'Py statement."""
    for item in analysis.lines:
        if item.kind != "code" or item.start_line >= len(raw_lines):
            continue
        raw = raw_lines[item.start_line]
        leading = len(raw) - len(raw.lstrip(" \t"))
        yield _LogicalCodeLine(
            item.start_line,
            utf16_length(raw[:leading]),
            raw[leading:],
        )


def _undefined_references(
    document: DocumentIndex,
    kind: str,
    declared: set[str],
    code: str,
    message: str | Callable[[str], str],
    severity: DiagnosticSeveritySetting,
    *,
    ignore_underscore: bool = False,
    ignore_reserved: bool = False,
) -> list[types.Diagnostic]:
    result: list[types.Diagnostic] = []
    seen: set[tuple[int, int, str]] = set()
    for reference in document.references:
        if reference.kind != kind or reference.container != kind:
            continue
        name = reference.name
        if ignore_underscore and name.startswith("_"):
            continue
        if ignore_reserved and name in _RENPY_STORE:
            continue
        if name in declared:
            continue
        key = (reference.line, reference.character, name)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            types.Diagnostic(
                range=types.Range(
                    start=types.Position(
                        line=reference.line, character=reference.character
                    ),
                    end=types.Position(
                        line=reference.line, character=reference.end_character
                    ),
                ),
                message=message(name) if callable(message) else message,
                severity=_SEVERITIES[severity],
                source=SOURCE,
                code=code,
            )
        )
    return result


def _severity(settings: Settings, rule: str) -> DiagnosticSeveritySetting | None:
    value = settings.diagnostic_rules.get(
        rule, DEFAULT_DIAGNOSTIC_RULES.get(rule, "off")
    )
    if rule == "unknown_label" and not settings.unknown_label_diagnostics:
        return None
    return value if value in _SEVERITIES else None


def _indent_diagnostic(
    line: int,
    raw_lines: Sequence[str],
    code: str,
    message: str,
    severity: DiagnosticSeveritySetting,
) -> types.Diagnostic:
    raw = raw_lines[line] if line < len(raw_lines) else ""
    leading = len(raw) - len(raw.lstrip(" \t"))
    end = utf16_length(raw[:leading]) if leading else 0
    if end == 0:
        end = min(1, utf16_length(raw))

    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=line, character=0),
            end=types.Position(line=line, character=end),
        ),
        message=message,
        severity=_SEVERITIES[severity],
        source=SOURCE,
        code=code,
    )


def _diagnostic(
    line: int,
    raw: str,
    start: int,
    end: int,
    code: str,
    message: str,
    severity: DiagnosticSeveritySetting,
) -> types.Diagnostic:
    start_units = utf16_length(raw[:start])
    end_units = start_units + utf16_length(raw[start:end])
    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=line, character=start_units),
            end=types.Position(line=line, character=end_units),
        ),
        message=message,
        severity=_SEVERITIES[severity],
        source=SOURCE,
        code=code,
    )
